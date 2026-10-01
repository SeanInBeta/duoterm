"""`duoterm` command line. Works for humans and for any agent that can run shell commands."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from . import tmux as tm
from .core import Result, DuotermError, Terminal

EPILOG = """\
typical agent loop:
  duoterm status                 is the terminal there and idle?
  duoterm read --new             what happened since I last looked (incl. what the user typed)
  duoterm run "df -h"            run a shell command, get its output and exit code
  duoterm screen                 look at the screen (vim, top, prompts, ...)
  duoterm type "y" --enter       answer an interactive prompt
  duoterm keys C-c               interrupt

exit codes: command's own exit code for `run`; 124 still running; 125 duoterm error.
"""


def _emit(args, result: Result) -> int:
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        text = result.to_text()
        if text:
            print(text)
    return result.process_exit


def _emit_text(args, text: str, **extra) -> int:
    if args.json:
        print(json.dumps({"status": "done", "output": text, **extra}, ensure_ascii=False))
    elif text:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="duoterm",
        description="Share a tmux terminal (e.g. an SSH session) between you and an AI agent.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-s", "--session", help="tmux session name (default: $DUOTERM_SESSION or 'remote')")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--version", action="version", version=f"duoterm {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="create/reuse the shared session and optionally ssh to a host")
    s.add_argument("host", nargs="?", help="ssh destination, e.g. myserver or user@1.2.3.4")
    s.add_argument("--ssh-arg", action="append", default=[], help="extra ssh argument (repeatable)")
    s.add_argument("--command", help="initial command for a new pane (default: your login shell)")
    s.add_argument("--reconnect", action="store_true", help="session exists but ssh dropped: send ssh again")

    sub.add_parser("attach", help="attach this terminal to the shared session (for the human)")
    sub.add_parser("stop", help="kill the shared session")
    sub.add_parser("status", help="session state: idle at prompt? pending agent command?")

    r = sub.add_parser("run", help="run a shell command and return its output + exit code")
    r.add_argument("command", nargs="+", help="command line (quote it, or pass words)")
    r.add_argument("-t", "--timeout", type=float, default=60, help="seconds to wait (default 60)")
    r.add_argument("--max-lines", type=int, default=200, help="keep only the last N output lines")
    r.add_argument("--force", action="store_true", help="skip the idle-prompt and dangerous-command checks")

    t = sub.add_parser("type", help="type literal text (for interactive programs)")
    t.add_argument("text")
    t.add_argument("--enter", action="store_true", help="press Enter afterwards")

    k = sub.add_parser("keys", help="send tmux key names: Enter C-c C-d Escape Tab Up Down q ...")
    k.add_argument("keys", nargs="+")

    sub.add_parser("screen", help="show the currently visible screen")

    rd = sub.add_parser("read", help="show recent output (scrollback) or only what is new")
    rd.add_argument("-n", "--lines", type=int, default=100, help="last N lines of scrollback (default 100)")
    rd.add_argument("--new", action="store_true", help="only output produced since the last `read --new`")
    rd.add_argument("--cursor", default="default", help="named read position for --new")

    w = sub.add_parser("wait", help="wait for the pending agent command, a pattern, or the terminal to go idle")
    w.add_argument("-t", "--timeout", type=float, default=60)
    w.add_argument("--idle", type=float, default=2.0, help="seconds of silence (at a prompt) that count as done")
    w.add_argument("--pattern", help="regex to wait for in new output")
    w.add_argument("--max-lines", type=int, default=200)

    c = sub.add_parser("context", help="new activity wrapped in <shared-terminal> tags (for prompt hooks)")
    c.add_argument("--cursor", default="hook")
    c.add_argument("--max-lines", type=int, default=80)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    term = Terminal(session=args.session)
    try:
        if args.cmd == "start":
            return _emit_text(args, term.start(args.host, args.ssh_arg, args.command, args.reconnect))
        if args.cmd == "attach":
            term.ensure()
            cmd = tm._base_cmd() + ["attach", "-t", f"={term.session}"]
            os.execvp(cmd[0], cmd)
        if args.cmd == "stop":
            return _emit_text(args, term.stop())
        if args.cmd == "status":
            st = term.status()
            if args.json:
                print(json.dumps(st, ensure_ascii=False))
            else:
                print("\n".join(f"{k}: {v}" for k, v in st.items()))
            return 0 if st["exists"] else 125
        if args.cmd == "run":
            command = args.command[0] if len(args.command) == 1 else " ".join(args.command)
            return _emit(args, term.run(command, timeout=args.timeout, force=args.force, max_lines=args.max_lines))
        if args.cmd == "type":
            term.type_text(args.text, enter=args.enter)
            return 0
        if args.cmd == "keys":
            term.keys(*args.keys)
            return 0
        if args.cmd == "screen":
            return _emit_text(args, term.screen())
        if args.cmd == "read":
            if args.new:
                return _emit_text(args, term.read_new(cursor=args.cursor))
            return _emit_text(args, term.read(args.lines))
        if args.cmd == "wait":
            return _emit(args, term.wait(args.timeout, args.idle, args.pattern, args.max_lines))
        if args.cmd == "context":
            # Used inside agent hooks: never fail the agent's prompt.
            try:
                text = term.context(cursor=args.cursor, max_lines=args.max_lines)
            except (DuotermError, tm.TmuxError, OSError):
                text = ""
            if text:
                print(text)
            return 0
    except (DuotermError, tm.TmuxError) as exc:
        if args.json:
            print(json.dumps(Result("error", message=str(exc)).to_dict(), ensure_ascii=False))
        else:
            print(f"duoterm: {exc}", file=sys.stderr)
        return 125
    return 0


if __name__ == "__main__":
    sys.exit(main())
