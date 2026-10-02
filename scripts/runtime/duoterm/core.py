"""Shared-terminal logic: run commands with completion markers, read output, wait, guard.

The terminal is a tmux pane (usually running `ssh host`). A human attaches to it with
`tmux attach`; agents drive it through this module via the CLI.

How `run` knows a command finished:
- shell integration active (see shell_integration.py): only the command is typed; the shell's
  invisible OSC 133 `D;<exit>` mark, seen in the pipe-pane log, ends it;
- otherwise: a visible `; printf '\n__RT_%s_%d__\n' <id> $?` suffix, found on screen.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import secrets
import shlex
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import shell_integration as si
from . import tmux as tm

DEFAULT_SESSION = "remote"
DEFAULT_PROMPT_RE = r"[$#%]$"
HISTORY_LIMIT = 50000
# TERM for the shared pane (and so, through ssh, for the remote shell). tmux's own default,
# tmux-256color, is missing from older servers' terminfo (e.g. CentOS 7); there bash's readline
# falls back to a dumb terminal and scrolls long lines sideways, hiding the prompt behind "<".
# tmux is screen-compatible, and screen-256color exists everywhere. DUOTERM_TERM overrides it;
# DUOTERM_TERM= (empty) keeps tmux's default-terminal.
DEFAULT_TERM = "screen-256color"
POLL_INTERVAL = 0.2
LOG_TAIL = 65536  # bytes of log scanned for the latest OSC 133 mark
MARK_GRACE = 1.0  # seconds the prompt may be back before a missing D mark counts as missing
OUTPUT_BYTES = 1 << 20  # an integrated command's output is cleaned from at most this many last bytes

# Commands that need --force. Deliberately short: this is a seatbelt against obvious
# accidents, not a sandbox. Real protection is your agent's permission settings.
DANGEROUS_PATTERNS = [
    (r"\brm\s+(-\S*\s+)*-\S*[rR]\S*\s+(-\S*\s+)*(/|/\*|~|~/|\*|\$HOME)(\s|$|;)", "recursive rm on /, ~ or *"),
    (r"\bmkfs(\.\w+)?\b", "mkfs (formats a filesystem)"),
    (r"\bdd\b.*\bof=/dev/", "dd writing to a device"),
    (r">\s*/dev/(sd|nvme|vd|xvd|hd)\w*", "redirect onto a block device"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "shutdown/reboot"),
    (r"\binit\s+[06]\b", "init 0/6"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bchmod\s+(-\S+\s+)*-R\s+(-\S+\s+)*0?777\s+/(\s|$)", "chmod -R 777 /"),
    (r"\bchown\s+(-\S+\s+)*-R\s+\S+\s+/(\s|$)", "chown -R on /"),
    (r"\bsystemctl\s+(stop|disable|mask)\s+(ssh|sshd)\b", "stopping sshd (locks you out)"),
    (r"\b(iptables|ip6tables)\s+(-\S+\s+)*-F\b", "flushing firewall rules"),
    (r"\bufw\s+(enable|reset)\b", "ufw enable/reset (may lock you out)"),
    (r"\bgit\s+push\s+.*--force\b|\bgit\s+push\s+(\S+\s+)*-f\b", "git force push"),
]

_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ESC_RE = re.compile(r"\x1b(?:[()][0-9A-Za-z]|[@-Z\\-_=>78])")
_BACKSPACE_RE = re.compile(r"[^\x08\n]\x08")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# zsh PROMPT_SP: an (inverse) %/# end-of-line mark, a row of spaces that wraps, then "\r \r".
_ZSH_PROMPT_SP_RE = re.compile(r"(?:(?:\x1b\[[0-9;]*m)+[^\s\x1b](?:\x1b\[[0-9;]*m)*)? {8,}\r \r")

# OSC 133 shell-integration marks: A prompt start, B prompt end, C command start, D;<exit> done.
_OSC133_RE = re.compile(rb"\x1b\]133;([A-D])((?:;[^\x07\x1b]*)?)(?:\x07|\x1b\\)")
_ESC_SEQ_RE = re.compile(rb"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[()].|.)", re.S)
# An escape sequence cut off by the end of the data (the rest is not in the log yet).
_PARTIAL_ESC_RE = re.compile(rb"\x1b(?:\][^\x07\x1b]*\x1b?|\[[0-?]*[ -/]*|[()])?\Z")


class DuotermError(Exception):
    """A problem with the request itself (no session, not idle, dangerous command...)."""


@dataclass
class Result:
    status: str  # "done" | "running" | "error"
    output: str = ""
    exit_code: int | None = None
    message: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_text(self) -> str:
        parts = [self.output.rstrip("\n")] if self.output.strip() else []
        if self.status == "done" and self.exit_code is not None:
            parts.append(f"[exit {self.exit_code}]")
        if self.message:
            parts.append(f"[{self.message}]")
        return "\n".join(parts)

    @property
    def process_exit(self) -> int:
        if self.status == "done":
            return min(max(self.exit_code or 0, 0), 255)
        return 124 if self.status == "running" else 125


def clean_terminal_text(raw: str) -> str:
    """Turn a raw terminal byte stream (as logged by pipe-pane) into readable text."""
    text = _ZSH_PROMPT_SP_RE.sub("\n", raw)
    text = _OSC_RE.sub("", text)
    text = _CSI_RE.sub("", text)
    text = _ESC_RE.sub("", text)
    while True:
        new = _BACKSPACE_RE.sub("", text)
        if new == text:
            break
        text = new
    text = text.replace("\r\n", "\n")
    lines = []
    for line in text.split("\n"):
        if "\r" in line:
            # Carriage return = overwrite (progress bars, readline redraws): keep the last version.
            segments = [s for s in line.split("\r") if s]
            line = segments[-1] if segments else ""
        lines.append(_CTRL_RE.sub("", line))
    return "\n".join(lines)


_WRAP_ECHO_RE = re.compile(r";\s*printf '\\n__RT_%s_%d__\\n' [0-9a-f]{8} \$\?")
_MARKER_LINE_RE = re.compile(r"\n?\n__RT_[0-9a-f]{8}_(\d+)__(?=\n|$)")


def prettify(text: str) -> str:
    """Hide duoterm's completion markers: drop the printf suffix, show `[exit N]` instead."""
    text = _WRAP_ECHO_RE.sub("", text)
    return _MARKER_LINE_RE.sub(lambda m: f"\n[exit {m.group(1)}]", text)


_EXIT_LINE_RE = re.compile(r"\n*(\[exit \d+\])\n+")
# The echo of the line `integrate` types (it erases it from the screen; hide it in log reads too).
_INTEGRATE_ECHO_RE = re.compile(r"^.*\\033\[F\\033\[2K%\.0s' \{1\.\.\d+\}.*\n?", re.M)


def _mark_exit(m: re.Match) -> int | None:
    code = m.group(2).lstrip(b";").split(b";")[0]
    return int(code) if code.isdigit() else None


def _typed_after(raw: bytes) -> bool:
    """Whether anything visible was printed in `raw` (e.g. after a prompt-end B mark)."""
    return bool(clean_terminal_text(raw.decode("utf-8", "replace")).strip())


def render_marks(raw: bytes, before: bytes = b"") -> bytes:
    """Replace OSC 133 marks: a command's D mark becomes an `[exit N]` line, the rest vanish.

    A D ends a command when a C came first, or (shells without C) something was typed after B.
    `before` is log text preceding `raw`; its last mark says whether `raw` starts mid-command.
    """
    out, pos, in_command, prompt_end = [], 0, False, None
    last = None
    for last in _OSC133_RE.finditer(before):
        pass
    if last is not None:
        in_command = last.group(1) == b"C"
        prompt_end = 0 if last.group(1) == b"B" else None
    for m in _OSC133_RE.finditer(raw):
        out.append(raw[pos : m.start()])
        kind = m.group(1)
        if kind == b"C":
            in_command = True
        elif kind == b"B":
            prompt_end = m.end()
        elif kind == b"D":
            code = _mark_exit(m)
            typed = prompt_end is not None and _typed_after(raw[prompt_end : m.start()])
            if (in_command or typed) and code is not None:
                out.append(b"\n[exit %d]\n" % code)
            in_command, prompt_end = False, None
        pos = m.end()
    out.append(raw[pos:])
    return b"".join(out)


def complete_prefix(raw: bytes) -> int:
    """Length of `raw` without a trailing half-written escape sequence or UTF-8 character."""
    m = _PARTIAL_ESC_RE.search(raw, max(0, len(raw) - 4096))
    end = m.start() if m else len(raw)
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    decoder.decode(raw[:end], final=False)
    return end - len(decoder.getstate()[0])


def check_dangerous(command: str) -> str | None:
    for pattern, why in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return why
    return None


def tail_lines(text: str, max_lines: int) -> str:
    lines = text.split("\n")
    if max_lines and len(lines) > max_lines:
        omitted = len(lines) - max_lines
        return f"[... {omitted} earlier lines omitted]\n" + "\n".join(lines[-max_lines:])
    return text


def _strip_blank_edges(lines: list[str]) -> list[str]:
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def _marker_command(marker_id: str) -> str:
    # The marker is printed with printf placeholders, so the echoed command line shows
    # "__RT_%s_%d__" while the output shows "__RT_<id>_<code>__": no false match.
    return f"printf '\\n__RT_%s_%d__\\n' {marker_id} $?"


def _wrap_command(command: str, marker_id: str | None = None) -> str:
    """The text to type: the command, plus the visible marker unless shell integration is on."""
    body = command.strip().rstrip(";").rstrip()
    if "\n" in body or "#" in body or body.endswith("&"):
        # A group survives comments, trailing '&' and multi-line scripts (one command, one D mark).
        body = "{ " + body + "\n}"
    return f"{body}; {_marker_command(marker_id)}" if marker_id else body


def _integrate_line(rows: int) -> str:
    """The setup code as one line, prefixed with a space (skips history where HISTCONTROL allows),
    ending in a printf that moves up `rows` rows (prompt + echo) and erases them one by one
    (erasing to the end of the screen from the top-left corner would push them into tmux history)."""
    return f" {si.one_line()}; printf '\\033[F\\033[2K%.0s' {{1..{rows}}}"


def _auto_integrate_enabled() -> bool:
    return os.environ.get("DUOTERM_AUTO_INTEGRATE", "1").strip().lower() not in ("0", "false", "no", "off")


def _parse_osc_run(raw: bytes, echo_lines: int) -> tuple[str, int | None]:
    """Output of an integrated command from its log bytes, and its exit code once D arrived.

    Output starts after the C mark (printed when the shell starts the command) or, if the
    shell sends none, after the echoed command lines; it ends at the first D mark.
    """
    marks = list(_OSC133_RE.finditer(raw))
    c = next((m for m in marks if m.group(1) == b"C"), None)
    if c:
        start = c.end()
    else:
        start = 0
        for _ in range(echo_lines):
            nl = raw.find(b"\n", start)
            if nl == -1:
                return "", None
            start = nl + 1
    d = next((m for m in marks if m.group(1) == b"D" and m.start() >= start), None)
    body = raw[start : d.start()] if d else raw[start : complete_prefix(raw)]
    if len(body) > OUTPUT_BYTES:  # only the tail is returned anyway; restart at a line boundary
        body = body[-OUTPUT_BYTES:]
        body = body[body.find(b"\n") + 1 :]
    text = clean_terminal_text(body.decode("utf-8", "replace"))
    output = "\n".join(_strip_blank_edges(text.split("\n")))
    return output, (_mark_exit(d) if d else None)


class Terminal:
    def __init__(self, session: str | None = None, home: str | os.PathLike | None = None):
        self.session = session or os.environ.get("DUOTERM_SESSION") or DEFAULT_SESSION
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.session):
            raise DuotermError("session names must contain only letters, digits, underscores or hyphens")
        self.home = Path(home or os.environ.get("DUOTERM_HOME") or Path.home() / ".duoterm")
        self.prompt_re = re.compile(os.environ.get("DUOTERM_PROMPT_RE") or DEFAULT_PROMPT_RE)

    # ----- files -------------------------------------------------------------------
    @property
    def log_path(self) -> Path:
        return self.home / f"{self.session}.log"

    @property
    def state_path(self) -> Path:
        return self.home / f"{self.session}.state.json"

    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        os.chmod(tmp, 0o600)
        tmp.replace(self.state_path)

    def _update_state(self, **changes) -> dict:
        state = self._load_state()
        for key, value in changes.items():
            if value is None:
                state.pop(key, None)
            else:
                state[key] = value
        self._save_state(state)
        return state

    # ----- session lifecycle -------------------------------------------------------
    def exists(self) -> bool:
        return tm.has_session(self.session)

    def ensure(self) -> None:
        if not self.exists():
            raise DuotermError(
                f"no tmux session '{self.session}'. Start one with: duoterm start <ssh-host>  "
                f"(or set DUOTERM_SESSION / -s to use another session)"
            )
        self._ensure_logging()

    def _ensure_logging(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        os.chmod(self.home, 0o700)
        if not self.log_path.exists():
            self.log_path.touch(mode=0o600)
        if tm.pane_info(self.session).get("pane_pipe") != "1":
            tm.pipe_pane(self.session, f"cat >> {shlex.quote(str(self.log_path))}")

    def start(
        self,
        host: str | None = None,
        ssh_args: list[str] | None = None,
        command: str | None = None,
        reconnect: bool = False,
        adopt: bool = False,
    ) -> str:
        created = False
        if not self.exists():
            tm.new_session(self.session, command, HISTORY_LIMIT, term=os.environ.get("DUOTERM_TERM", DEFAULT_TERM))
            created = True
        elif tm.get_option(self.session, "@duoterm") != "1" and not adopt:
            raise DuotermError("existing session is not managed by duoterm; confirm its identity, then use start --adopt")
        tm.set_option(self.session, "@duoterm", "1")
        if created or (host and reconnect):
            tm.set_option(self.session, "@duoterm_target", host or "")
        self._ensure_logging()
        lines = [f"session '{self.session}' {'created' if created else 'already running'}; log: {self.log_path}"]
        if host:
            if not created and not reconnect:
                # Re-sending ssh into a live session would nest ssh inside the remote shell.
                lines.append("ssh not re-sent; if the connection dropped, use --reconnect (or type ssh yourself)")
            elif not created and not self.is_idle()[0]:
                lines.append("pane is busy (not at a shell prompt), so ssh was not started")
            else:
                self._wait_for_prompt(5.0)
                ssh = " ".join(shlex.quote(a) for a in ["ssh", *(ssh_args or []), host])
                tm.send_literal(self.session, ssh)
                tm.send_keys(self.session, "Enter")
                lines.append(f"sent: {ssh}")
        lines.append(f"attach to it yourself with: {self.attach_command()}")
        return "\n".join(lines)

    def attach_command(self) -> str:
        sock = os.environ.get("DUOTERM_TMUX_SOCKET")
        return f"tmux {'-L ' + sock + ' ' if sock else ''}attach -t {self.session}"

    def stop(self) -> str:
        if self.exists():
            tm.tmux("kill-session", "-t", f"={self.session}")
        self._update_state(pending=None, status_saved=None)
        return f"session '{self.session}' stopped"

    # ----- observation -------------------------------------------------------------
    def screen(self) -> str:
        self.ensure()
        info = tm.pane_info(self.session)
        text = tm.capture(self.session).rstrip("\n")
        return f"{text}\n[cursor row {info['cursor_y']} col {info['cursor_x']}, {info['pane_width']}x{info['pane_height']}]"

    def read(self, lines: int = 100) -> str:
        """Last N rendered lines (scrollback + screen), as the human sees them."""
        self.ensure()
        text = prettify(tm.capture(self.session, start=-max(lines, 1)))
        return "\n".join(_strip_blank_edges(text.split("\n"))[-lines:])

    def read_new(self, cursor: str = "default", max_lines: int = 200, advance: bool = True) -> str:
        """Everything printed since this cursor last read (from the pipe-pane log)."""
        self.ensure()
        cursors = self._load_state().get("cursors", {})
        offset = cursors.get(cursor, 0)
        if offset > self._log_size():  # log truncated/rotated
            offset = 0
        text, end = self._log_since(offset)
        if advance:
            cursors[cursor] = end
            self._update_state(cursors=cursors)
        return tail_lines(text, max_lines)

    def _log_since(self, offset: int) -> tuple[str, int]:
        """Readable log text from `offset` on, and the offset to continue from next time."""
        offset = self._align(offset)
        raw = self._read_log(offset)
        raw = raw[: complete_prefix(raw)]  # a half-written sequence waits for the next read
        before = self._read_log(max(0, offset - 4096), offset)
        text = clean_terminal_text(render_marks(raw, before).decode("utf-8", "replace"))
        text = prettify(_EXIT_LINE_RE.sub(r"\n\1\n", _INTEGRATE_ECHO_RE.sub("", text)))
        return "\n".join(_strip_blank_edges(text.split("\n"))), offset + len(raw)

    def _log_size(self) -> int:
        return self.log_path.stat().st_size

    def _read_log(self, start: int, end: int | None = None) -> bytes:
        with open(self.log_path, "rb") as fh:
            fh.seek(start)
            return fh.read() if end is None else fh.read(max(end - start, 0))

    def _align(self, offset: int) -> int:
        """Move an offset that falls inside an escape sequence or a UTF-8 character past it."""
        if offset <= 0:
            return 0
        before = self._read_log(max(0, offset - 4096), offset)
        rest = self._read_log(offset, offset + 4096)
        partial = _PARTIAL_ESC_RE.search(before)
        if partial:
            m = _ESC_SEQ_RE.match(before[partial.start() :] + rest)
            if m:
                return offset + max(m.end() - (len(before) - partial.start()), 0)
        skip = 0
        while skip < len(rest) and 0x80 <= rest[skip] <= 0xBF:  # UTF-8 continuation bytes
            skip += 1
        return offset + skip

    def _integration(self) -> tuple[bool, int, int]:
        """(active, position of the latest OSC 133 mark, log size).

        Active when the latest mark is a prompt mark (A/B): the shell sitting at this prompt
        is integrated. After C (a command started: ssh, sudo -i, a subshell, vim...) whatever
        prompt shows up next belongs to something else until that shell prints A again.
        """
        size = self._log_size()
        start = max(0, size - LOG_TAIL)
        last = None
        for last in _OSC133_RE.finditer(self._read_log(start, size)):
            pass
        if last is None or last.group(1) not in (b"A", b"B"):
            return False, -1, size
        if last.group(1) == b"B" and _typed_after(self._read_log(start + last.end(), size)):
            # Output after the prompt's end: a command ran that the shell never reported
            # (no C mark in bash < 4.4), e.g. ssh or sudo -i, and this is its prompt.
            return False, -1, size
        at = start + last.start()
        if at <= self._load_state().get("integration_lost_at", -1):
            return False, at, size
        return True, at, size

    def is_idle(self) -> tuple[bool, str]:
        """True when the cursor sits on an empty shell prompt (nothing half-typed)."""
        cy = int(tm.pane_info(self.session)["cursor_y"])
        # Capture just the cursor row: in a full capture, wrapped rows are joined (-J), so long
        # lines further up would shift the row index.
        line = tm.capture(self.session, start=cy, end=cy).split("\n")[0].rstrip()
        return bool(self.prompt_re.search(line)), line

    def status(self, observe_only: bool = False) -> dict:
        if not self.exists():
            return {"session": self.session, "exists": False, "attach": self.attach_command()}
        if not observe_only:
            self._ensure_logging()
        info = tm.pane_info(self.session)
        idle, line = self.is_idle()
        pending = self._load_state().get("pending")
        clients = int(tm.tmux("display-message", "-p", "-t", tm.target(self.session), "#{session_attached}").strip())
        expected_host = tm.get_option(self.session, "@duoterm_target")
        foreground = info["pane_current_command"]
        connection = ("ssh_unknown_target" if foreground == "ssh" else "local") if not expected_host else "unknown"
        screen = tm.capture(self.session, start=-12)
        if expected_host:
            if foreground != "ssh":
                connection = "disconnected"
            elif not idle and re.search(r"password:|passphrase|yes/no|verification code", screen, re.I):
                connection = "awaiting_authentication"
            elif idle:
                connection = "ssh_prompt"
            else:
                connection = "ssh_busy_or_connecting"
        return {
            "session": self.session,
            "exists": True,
            "attached_clients": clients,
            "attached": clients > 0,
            "connection_state": connection,
            "expected_host": expected_host or None,
            "idle_at_prompt": idle,
            "current_line": line,
            "local_foreground_command": info["pane_current_command"],
            "pending_agent_command": pending["command"] if pending else None,
            "shell_integration": self._integration()[0] if self.log_path.exists() else False,
            "log": str(self.log_path),
            "attach": self.attach_command(),
        }

    def list_sessions(self) -> list[dict]:
        sessions = []
        for item in tm.list_sessions():
            if item.get("managed") == "1":
                terminal = Terminal(item["session"], home=self.home)
                try:
                    sessions.append(terminal.status(observe_only=True))
                except tm.TmuxError:
                    continue  # The human may close a window during inspection.
        return sessions

    # ----- input -------------------------------------------------------------------
    def type_text(self, text: str, enter: bool = False) -> None:
        self.ensure()
        tm.send_literal(self.session, text)
        if enter:
            tm.send_keys(self.session, "Enter")

    def keys(self, *keys: str) -> None:
        self.ensure()
        tm.send_keys(self.session, *keys)

    # ----- run / wait ----------------------------------------------------------------
    def run(self, command: str, timeout: float = 60.0, force: bool = False, max_lines: int = 200) -> Result:
        self.ensure()
        if not command.strip():
            raise DuotermError("empty command")
        if not force:
            why = check_dangerous(command)
            if why:
                raise DuotermError(f"refused: looks dangerous ({why}). Confirm with the user, then re-run with --force")
            self._require_idle_prompt()

        integrated, mark_at, log_size = self._integration()
        if not integrated and not force and _auto_integrate_enabled():
            integrated, mark_at, log_size = self._auto_integrate()
        info = tm.pane_info(self.session)
        start_abs = int(info["history_size"]) + int(info["cursor_y"])
        prompt = self.is_idle()[1]
        self._set_busy_status(command)
        pending = {"start_abs": start_abs, "prompt": prompt, "command": command, "started": time.time()}
        if integrated:
            text = _wrap_command(command)
            # Everything the shell prints for this command lands in the log after log_size.
            pending.update(mode="osc", offset=log_size, mark_at=mark_at, lines=text.count("\n") + 1)
        else:
            pending["id"] = secrets.token_hex(4)
            text = _wrap_command(command, pending["id"])
        self._update_state(pending=pending)
        tm.send_literal(self.session, text)
        tm.send_keys(self.session, "Enter")
        return self._wait_pending(pending, timeout, max_lines)

    def _require_idle_prompt(self) -> None:
        idle, line = self.is_idle()
        deadline = time.time() + 0.5
        while not idle and not line.strip() and time.time() < deadline:
            # A command that just finished: its prompt may be a moment from being drawn.
            time.sleep(0.05)
            idle, line = self.is_idle()
        if self._load_state().get("pending"):
            if not idle:
                raise DuotermError("a previous agent command is still running; use `duoterm wait` (or `duoterm keys C-c`)")
            # Back at a prompt without anyone collecting the marker (e.g. interrupted): forget it.
            self._update_state(pending=None)
            self._restore_status()
        if not idle:
            raise DuotermError(
                f"terminal is not at an idle shell prompt (current line: {line!r}). "
                "Something is running, the user is typing, or an interactive program is open. "
                "Inspect with `duoterm screen`; use `duoterm type/keys` for interactive programs, "
                "or --force if the prompt is just unusual (or set DUOTERM_PROMPT_RE)"
            )

    def integrate(self, force: bool = False, timeout: float = 5.0) -> str:
        """Type the shell-integration setup into the shared shell (once per shell, e.g. after ssh)."""
        self.ensure()
        if self._integration()[0]:
            return "shell integration already active: commands run without a visible marker"
        if not force:
            self._require_idle_prompt()
        if self._send_integration(timeout):
            return "shell integration active: commands now run without a visible marker"
        return (
            "setup code sent, but no OSC 133 prompt mark appeared (needs bash or zsh); "
            "duoterm keeps using its visible printf marker in this shell"
        )

    def _auto_integrate(self) -> tuple[bool, int, int]:
        """`run` in a shell without integration: set it up first, unless DUOTERM_AUTO_INTEGRATE=0
        or it already failed at this same prompt (a shell that cannot do it, e.g. sh or fish)."""
        prompt = self.is_idle()[1]
        if self._load_state().get("auto_integrate_failed") != prompt:
            ok = self._send_integration(timeout=3.0)
            self._update_state(auto_integrate_failed=None if ok else prompt)
            if not ok:
                self._wait_for_prompt(2.0)
        return self._integration()

    def _send_integration(self, timeout: float) -> bool:
        """Type the setup line at the prompt, erase it again, and wait for the first prompt mark."""
        info = tm.pane_info(self.session)
        top = int(info["history_size"]) + int(info["cursor_y"])
        # Guess the rows the typed line takes if it wraps; then measure, since readline may also
        # scroll it horizontally on one row. Retype with the right count if the guess was off.
        rows = (int(info["cursor_x"]) + len(_integrate_line(9))) // max(int(info["pane_width"]), 1) + 1
        for attempt in range(3):
            tm.send_literal(self.session, _integrate_line(rows))
            used = self._settled_row() - top + 1
            if used == rows or attempt == 2:
                break
            tm.send_keys(self.session, "C-u")
            top = self._settled_row()
            rows = used
        tm.send_keys(self.session, "Enter")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._integration()[0] and self.is_idle()[0]:
                return True
            time.sleep(POLL_INTERVAL)
        # pipe-pane or a slow tmux query may finish during the final poll.
        # Observe that completed setup once more before classifying it as failed.
        return self._integration()[0] and self.is_idle()[0]

    def _settled_row(self, timeout: float = 2.0) -> int:
        """Absolute cursor row once the shell has stopped redrawing the input line."""
        last, deadline = None, time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.1)
            info = tm.pane_info(self.session)
            pos = (int(info["history_size"]) + int(info["cursor_y"]), info["cursor_x"])
            if pos == last:
                break
            last = pos
        return last[0]

    def wait(self, timeout: float = 60.0, idle: float = 2.0, pattern: str | None = None, max_lines: int = 200) -> Result:
        """Wait for the pending agent command, a regex in new output, or the terminal going quiet."""
        self.ensure()
        pending = self._load_state().get("pending")
        if pending and not pattern:
            return self._wait_pending(pending, timeout, max_lines)

        regex = re.compile(pattern) if pattern else None
        start_offset = self._log_size()
        last_size, last_change = start_offset, time.time()
        deadline = time.time() + timeout
        while True:
            size = self._log_size()
            now = time.time()
            if size != last_size:
                last_size, last_change = size, now
            if regex:
                new = clean_terminal_text(self._log_since(start_offset)[0])
                if regex.search(new):
                    return Result("done", self._since_or_screen(start_offset, max_lines), message=f"pattern {pattern!r} appeared")
            elif now - last_change >= idle and self.is_idle()[0]:
                return Result("done", self._since_or_screen(start_offset, max_lines), message="terminal idle at prompt")
            if now >= deadline:
                return Result("running", self._since_or_screen(start_offset, max_lines), message=f"still waiting after {timeout:g}s")
            time.sleep(POLL_INTERVAL)

    def _since_or_screen(self, offset: int, max_lines: int) -> str:
        # Output produced during the wait; if there was none, the bottom of the screen.
        text = self._log_since(offset)[0]
        return tail_lines(text, max_lines) if text.strip() else self.read(20)

    def _wait_pending(self, pending: dict, timeout: float, max_lines: int) -> Result:
        if pending.get("mode") == "osc":
            return self._wait_osc(pending, timeout, max_lines)
        return self._wait_marker(pending, timeout, max_lines)

    def _wait_osc(self, pending: dict, timeout: float, max_lines: int) -> Result:
        """Wait for the shell's OSC 133 D mark after the command (shell integration mode)."""
        deadline = time.time() + timeout
        prompt_back_at = None
        raw = b""
        while True:
            new = self._read_log(pending["offset"] + len(raw))
            raw += new
            if b"\x1b]133;D" in raw[-(len(new) + 16) :]:  # parse only when a D mark may have arrived
                output, exit_code = _parse_osc_run(raw, pending["lines"])
                if exit_code is not None:
                    self._update_state(pending=None)
                    self._restore_status()
                    return Result("done", tail_lines(output, max_lines), exit_code=exit_code)
            now = time.time()
            if self._back_at_original_prompt(pending):
                # D is printed before the prompt, so it should be logged by now (allow for lag).
                prompt_back_at = prompt_back_at or now
                if now - prompt_back_at >= MARK_GRACE:
                    return self._exit_code_without_marks(pending, max_lines)
            else:
                prompt_back_at = None
            if now >= deadline:
                self._set_busy_status(pending["command"], still=True)
                return Result(
                    "running",
                    tail_lines(_parse_osc_run(raw, pending["lines"])[0], max_lines),
                    message=f"still running after {timeout:g}s; `duoterm wait` to keep waiting, `duoterm keys C-c` to interrupt",
                )
            time.sleep(POLL_INTERVAL)

    def _exit_code_without_marks(self, pending: dict, max_lines: int) -> Result:
        """The prompt came back but no D mark: the shell here is not integrated after all (e.g. ssh
        dropped back to a local shell). Stop trusting its marks and ask for $? with the printf marker."""
        self._update_state(integration_lost_at=pending["mark_at"])
        rows = self._capture_from(pending["start_abs"])
        prompt_row = max((i for i, row in enumerate(rows) if row.rstrip() == pending["prompt"]), default=len(rows))
        output = "\n".join(_strip_blank_edges(rows[pending["lines"] : prompt_row]))
        info = tm.pane_info(self.session)
        probe = {
            "id": secrets.token_hex(4),
            "start_abs": int(info["history_size"]) + int(info["cursor_y"]),
            "prompt": pending["prompt"],
            "command": pending["command"],
            "started": pending["started"],
        }
        self._update_state(pending=probe)
        tm.send_literal(self.session, _marker_command(probe["id"]))
        tm.send_keys(self.session, "Enter")
        result = self._wait_marker(probe, 10.0, max_lines)
        if result.status != "done":
            return result
        result.output = tail_lines(output, max_lines)
        result.message = "no shell integration here after all; exit status read with the visible marker"
        return result

    def _wait_marker(self, pending: dict, timeout: float, max_lines: int) -> Result:
        marker_re = re.compile(rf"__RT_{pending['id']}_(\d+)__")

        def finish(lines: list[str], exit_code: int, message: str = "") -> Result:
            self._update_state(pending=None)
            self._restore_status()
            output = "\n".join(self._output_lines(lines, pending["id"]))
            return Result("done", tail_lines(output, max_lines), exit_code=exit_code, message=message)

        deadline = time.time() + timeout
        while True:
            lines = self._capture_from(pending["start_abs"])
            found = self._find_marker(lines, marker_re)
            if found:
                return finish(lines[: found[0]], found[1])
            if self._back_at_original_prompt(pending):
                # Re-check: the marker may have landed between the two captures.
                lines = self._capture_from(pending["start_abs"])
                found = self._find_marker(lines, marker_re)
                if found:
                    return finish(lines[: found[0]], found[1])
                prompt_row = max(i for i, line in enumerate(lines) if line.rstrip() == pending["prompt"])
                return finish(lines[:prompt_row], 130, "interrupted: prompt came back without an exit status")
            if time.time() >= deadline:
                self._set_busy_status(pending["command"], still=True)
                output = "\n".join(self._output_lines(lines, pending["id"]))
                return Result(
                    "running",
                    tail_lines(output, max_lines),
                    message=f"still running after {timeout:g}s; `duoterm wait` to keep waiting, `duoterm keys C-c` to interrupt",
                )
            time.sleep(POLL_INTERVAL)

    @staticmethod
    def _find_marker(lines: list[str], marker_re: re.Pattern) -> tuple[int, int] | None:
        for i, line in enumerate(lines):
            m = marker_re.search(line)
            if m:
                return i, int(m.group(1))
        return None

    def _back_at_original_prompt(self, pending: dict) -> bool:
        """The command was cut short (Ctrl-C) when the same prompt reappears on a later row."""
        if not pending.get("prompt"):
            return False
        info = tm.pane_info(self.session)
        if int(info["history_size"]) + int(info["cursor_y"]) <= pending["start_abs"]:
            return False
        idle, line = self.is_idle()
        return idle and line == pending["prompt"]

    def _capture_from(self, start_abs: int) -> list[str]:
        # Output can scroll between reading history_size and capturing the pane.
        # Retry that snapshot instead of dropping early output with a stale offset.
        for _ in range(5):
            history = int(tm.pane_info(self.session)["history_size"])
            rel = start_abs - history
            start: int | str = rel if rel >= -history else "-"
            lines = tm.capture(self.session, start=start).split("\n")
            if int(tm.pane_info(self.session)["history_size"]) == history:
                return lines
        return lines

    @staticmethod
    def _output_lines(lines: list[str], marker_id: str) -> list[str]:
        # Drop the echoed (wrapped) command: everything up to the last line mentioning the id.
        echo_end = -1
        for i, line in enumerate(lines):
            if marker_id in line:
                echo_end = i
        return _strip_blank_edges(list(lines[echo_end + 1 :]))

    # ----- tmux status bar hint ----------------------------------------------------
    def _set_busy_status(self, command: str, still: bool = False) -> None:
        state = self._load_state()
        if "status_saved" not in state:
            self._update_state(status_saved={"value": tm.get_option(self.session, "status-right")})
        short = command.strip().splitlines()[0][:40].replace("#", "##")
        label = "AGENT CMD STILL RUNNING" if still else "AGENT RUNNING"
        tm.set_option(self.session, "status-right", f"#[bg=red,fg=white,bold] {label}: {short} #[default]")

    def _restore_status(self) -> None:
        saved = self._load_state().get("status_saved")
        if saved is None:
            return
        if saved.get("value"):
            tm.set_option(self.session, "status-right", saved["value"])
        else:
            tm.unset_option(self.session, "status-right")
        self._update_state(status_saved=None)

    def _wait_for_prompt(self, timeout: float) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_idle()[0]:
                return
            time.sleep(POLL_INTERVAL)

    # ----- hook / context helper -----------------------------------------------------
    def context(self, cursor: str = "hook", max_lines: int = 80) -> str:
        """New terminal activity since the last call, wrapped for injection into an agent prompt."""
        if not self.exists():
            return ""
        text = self.read_new(cursor=cursor, max_lines=max_lines)
        if not text.strip():
            return ""
        return f'<shared-terminal session="{self.session}">\n{text}\n</shared-terminal>'
