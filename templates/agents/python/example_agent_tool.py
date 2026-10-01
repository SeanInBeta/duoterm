"""Using the shared terminal from your own Python agent (PyAgent, LangChain, a custom loop, ...).

Option A - import it (same machine / WSL):
"""

from duoterm.core import DuotermError, Terminal

term = Terminal(session="remote")


def terminal_run(command: str, timeout: float = 60) -> str:
    """Tool for your agent: run a command in the shared SSH terminal."""
    try:
        return term.run(command, timeout=timeout).to_text()
    except DuotermError as exc:
        return f"error: {exc}"


def terminal_read_new() -> str:
    """Tool for your agent: what happened in the terminal since the last call."""
    return term.read_new(cursor="pyagent") or "[nothing new]"


# Option B - any language, via the CLI's JSON output:
#   subprocess.run(["duoterm", "--json", "run", "df -h"], capture_output=True, text=True)
#   -> {"status": "done", "output": "...", "exit_code": 0, "message": "", "extra": {}}

if __name__ == "__main__":
    print(terminal_run("uname -a"))
