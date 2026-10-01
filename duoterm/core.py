"""Shared-terminal logic: run commands with completion markers, read output, wait, guard.

The terminal is a tmux pane (usually running `ssh host`). A human attaches to it with
`tmux attach`; agents drive it through this module (via the CLI or the MCP server).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import tmux as tm

DEFAULT_SESSION = "remote"
DEFAULT_PROMPT_RE = r"[$#%]$"
HISTORY_LIMIT = 50000
POLL_INTERVAL = 0.2

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
    text = _OSC_RE.sub("", raw)
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


def _wrap_command(command: str, marker_id: str) -> str:
    # The marker is printed with printf placeholders, so the echoed command line shows
    # "__RT_%s_%d__" while the output shows "__RT_<id>_<code>__": no false match.
    marker = f"printf '\\n__RT_%s_%d__\\n' {marker_id} $?"
    body = command.strip().rstrip(";").rstrip()
    if "\n" in body or "#" in body or body.endswith("&"):
        # A group survives comments, trailing '&' and multi-line scripts.
        return "{ " + body + "\n}; " + marker
    return f"{body}; {marker}"


class Terminal:
    def __init__(self, session: str | None = None, home: str | os.PathLike | None = None):
        self.session = session or os.environ.get("DUOTERM_SESSION") or DEFAULT_SESSION
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
    ) -> str:
        created = False
        if not self.exists():
            tm.new_session(self.session, command, HISTORY_LIMIT)
            created = True
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
        if offset > self.log_path.stat().st_size:  # log truncated/rotated
            offset = 0
        text, end = self._log_since(offset)
        if advance:
            cursors[cursor] = end
            self._update_state(cursors=cursors)
        return tail_lines(text, max_lines)

    def _log_since(self, offset: int) -> tuple[str, int]:
        with open(self.log_path, "rb") as fh:
            fh.seek(offset)
            raw = fh.read()
        text = prettify(clean_terminal_text(raw.decode("utf-8", "replace")))
        return "\n".join(_strip_blank_edges(text.split("\n"))), offset + len(raw)

    def is_idle(self) -> tuple[bool, str]:
        """True when the cursor sits on an empty shell prompt (nothing half-typed)."""
        info = tm.pane_info(self.session)
        rows = tm.capture(self.session).split("\n")
        cy = int(info["cursor_y"])
        line = rows[cy].rstrip() if cy < len(rows) else ""
        return bool(self.prompt_re.search(line)), line

    def status(self) -> dict:
        if not self.exists():
            return {"session": self.session, "exists": False, "attach": self.attach_command()}
        self._ensure_logging()
        info = tm.pane_info(self.session)
        idle, line = self.is_idle()
        pending = self._load_state().get("pending")
        return {
            "session": self.session,
            "exists": True,
            "idle_at_prompt": idle,
            "current_line": line,
            "local_foreground_command": info["pane_current_command"],
            "pending_agent_command": pending["command"] if pending else None,
            "log": str(self.log_path),
            "attach": self.attach_command(),
        }

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

        marker_id = secrets.token_hex(4)
        info = tm.pane_info(self.session)
        start_abs = int(info["history_size"]) + int(info["cursor_y"])
        prompt = self.is_idle()[1]
        self._set_busy_status(command)
        pending = {"id": marker_id, "start_abs": start_abs, "prompt": prompt, "command": command, "started": time.time()}
        self._update_state(pending=pending)
        tm.send_literal(self.session, _wrap_command(command, marker_id))
        tm.send_keys(self.session, "Enter")
        return self._wait_marker(pending, timeout, max_lines)

    def wait(self, timeout: float = 60.0, idle: float = 2.0, pattern: str | None = None, max_lines: int = 200) -> Result:
        """Wait for the pending agent command, a regex in new output, or the terminal going quiet."""
        self.ensure()
        pending = self._load_state().get("pending")
        if pending and not pattern:
            return self._wait_marker(pending, timeout, max_lines)

        regex = re.compile(pattern) if pattern else None
        start_offset = self.log_path.stat().st_size
        last_size, last_change = start_offset, time.time()
        deadline = time.time() + timeout
        while True:
            size = self.log_path.stat().st_size
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
        history = int(tm.pane_info(self.session)["history_size"])
        rel = start_abs - history
        start: int | str = rel if rel >= -history else "-"
        return tm.capture(self.session, start=start).split("\n")

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
