"""Thin wrapper around the tmux command line.

Every call goes through `tmux(...)` so the socket (`DUOTERM_TMUX_SOCKET` -> `tmux -L`)
is honoured everywhere; tests use that to run on an isolated tmux server.
"""

from __future__ import annotations

import os
import shutil
import subprocess


class TmuxError(RuntimeError):
    pass


def _base_cmd() -> list[str]:
    if shutil.which("tmux") is None:
        raise TmuxError("tmux is not installed (Ubuntu/WSL: sudo apt install tmux)")
    cmd = ["tmux"]
    socket = os.environ.get("DUOTERM_TMUX_SOCKET")
    if socket:
        cmd += ["-L", socket]
    return cmd


def tmux(*args: str, check: bool = True) -> str:
    proc = subprocess.run(_base_cmd() + list(args), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise TmuxError(f"tmux {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout


def has_session(session: str) -> bool:
    proc = subprocess.run(_base_cmd() + ["has-session", "-t", f"={session}"], capture_output=True)
    return proc.returncode == 0


def new_session(
    session: str, command: str | None, history_limit: int, width: int = 200, height: int = 50, term: str | None = None
) -> None:
    # history-limit only applies to panes created after it is set, so boot the session
    # with a throwaway window, set the option, open the real window, drop the boot one.
    tmux("new-session", "-d", "-s", session, "-n", "_boot", "-x", str(width), "-y", str(height), "sleep 60")
    tmux("set-option", "-t", session, "history-limit", str(history_limit))
    args = ["new-window", "-t", f"={session}:", "-n", "shell"]
    if term:
        # Only this window: default-terminal is a server option and would change the user's other sessions.
        args += ["-e", f"TERM={term}"]
    if command:
        args.append(command)
    tmux(*args)
    tmux("kill-window", "-t", f"={session}:_boot")


def target(session: str) -> str:
    # "=name:" pins the exact session and resolves to its active pane.
    return f"={session}:"


def send_literal(session: str, text: str) -> None:
    """Type text exactly as given (no key-name interpretation)."""
    if not text:
        return
    # tmux treats an argument ending in ';' as a command separator and swallows it,
    # so a trailing ';' is sent separately as a hex key.
    trailing = len(text) - len(text.rstrip(";"))
    body = text[: len(text) - trailing]
    if body:
        tmux("send-keys", "-t", target(session), "-l", "--", body)
    if trailing:
        tmux("send-keys", "-t", target(session), "-H", *(["3b"] * trailing))


def send_keys(session: str, *keys: str) -> None:
    """Send tmux key names such as Enter, C-c, Up, Escape, Tab."""
    if keys:
        tmux("send-keys", "-t", target(session), *keys)


def capture(session: str, start: int | str | None = None, end: int | str | None = None) -> str:
    """Rendered pane text. Line 0 is the first visible line, negative numbers reach into history."""
    args = ["capture-pane", "-p", "-J", "-t", target(session)]
    if start is not None:
        args += ["-S", str(start)]
    if end is not None:
        args += ["-E", str(end)]
    return tmux(*args)


def pane_info(session: str) -> dict[str, str]:
    fields = [
        "history_size",
        "history_limit",
        "cursor_x",
        "cursor_y",
        "pane_height",
        "pane_width",
        "pane_current_command",
        "pane_pipe",
        "pane_dead",
    ]
    out = tmux("display-message", "-p", "-t", target(session), "\t".join("#{%s}" % f for f in fields))
    return dict(zip(fields, out.rstrip("\n").split("\t")))


def pipe_pane(session: str, shell_command: str) -> None:
    # -o: only open a pipe if none is open, so repeated calls are harmless.
    tmux("pipe-pane", "-o", "-t", target(session), shell_command)


def get_option(session: str, name: str) -> str:
    return tmux("show-options", "-v", "-t", session, name, check=False).rstrip("\n")


def set_option(session: str, name: str, value: str) -> None:
    tmux("set-option", "-t", session, name, value)


def unset_option(session: str, name: str) -> None:
    tmux("set-option", "-u", "-t", session, name, check=False)
