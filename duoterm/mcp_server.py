"""MCP server exposing the shared terminal as tools (stdio transport).

Register with any MCP-capable agent, e.g. `claude mcp add duoterm -- duoterm-mcp`
or `codex mcp add duoterm -- duoterm-mcp`. Requires `pip install 'duoterm[mcp]'`.
"""

from __future__ import annotations

import functools

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import shell_integration as si
from . import tmux as tm
from .core import DuotermError, Terminal

INSTRUCTIONS = """\
A tmux terminal shared with the user, usually an SSH session to a remote server.
The user watches it live and may type into it too.
- Start with terminal_status, then terminal_read(new_only=True) to see what happened since you last looked.
- terminal_run executes one shell command at an idle prompt and returns its output and exit code.
- For interactive programs (vim, top, sudo/password prompts, y/n questions, REPLs) use
  terminal_screen + terminal_type/terminal_keys instead of terminal_run.
- Never type passwords or secrets; ask the user to type them in the terminal.
- If terminal_run says the terminal is busy, look at terminal_screen before doing anything else.
- If terminal_status shows shell_integration: False, terminal_run leaves a visible printf/__RT_ marker
  after each command. Suggest the user runs `duoterm integrate` once in that shell (or, with their
  approval, call terminal_integrate); to make it permanent, terminal_integrate(print_only=True) gives
  the code for their ~/.bashrc / ~/.zshrc on the server.
"""

mcp = FastMCP("duoterm", instructions=INSTRUCTIONS)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (DuotermError, tm.TmuxError) as exc:
        raise ToolError(str(exc)) from exc


async def _in_thread(fn, *args, **kwargs):
    # Waiting polls with time.sleep; keep it off the event loop.
    return await anyio.to_thread.run_sync(functools.partial(_call, fn, *args, **kwargs))


@mcp.tool(annotations=READ_ONLY)
async def terminal_status(session: str | None = None) -> str:
    """Whether the shared terminal exists, is idle at a shell prompt, and if an agent command is pending."""
    st = await _in_thread(Terminal(session).status)
    return "\n".join(f"{k}: {v}" for k, v in st.items())


@mcp.tool(annotations=WRITES)
async def terminal_run(command: str, timeout: float = 60, force: bool = False, session: str | None = None) -> str:
    """Run a shell command in the shared terminal and return its output followed by [exit N].

    Only works at an idle shell prompt. If it does not finish within `timeout` seconds the result says
    it is still running: call terminal_wait to keep waiting or terminal_keys(["C-c"]) to interrupt.
    `force` skips the idle and dangerous-command checks; only use it after the user confirmed.
    """
    result = await _in_thread(Terminal(session).run, command, timeout=timeout, force=force)
    return result.to_text() or "[no output]"


@mcp.tool(annotations=WRITES)
async def terminal_type(text: str, enter: bool = False, session: str | None = None) -> str:
    """Type literal text into the terminal (answers to prompts, input for REPLs/editors). Returns the screen."""
    term = Terminal(session)
    await _in_thread(term.type_text, text, enter=enter)
    await anyio.sleep(0.5)
    return await _in_thread(term.screen)


@mcp.tool(annotations=WRITES)
async def terminal_keys(keys: list[str], session: str | None = None) -> str:
    """Send tmux key names, e.g. ["C-c"], ["Escape", ":wq", "Enter"], ["Up"], ["q"]. Returns the screen."""
    term = Terminal(session)
    await _in_thread(term.keys, *keys)
    await anyio.sleep(0.5)
    return await _in_thread(term.screen)


@mcp.tool(annotations=READ_ONLY)
async def terminal_screen(session: str | None = None) -> str:
    """The currently visible screen, exactly as the user sees it, plus the cursor position."""
    return await _in_thread(Terminal(session).screen)


@mcp.tool(annotations=READ_ONLY)
async def terminal_read(lines: int = 100, new_only: bool = False, session: str | None = None) -> str:
    """Recent terminal output. new_only=True returns only what appeared since your last new_only read,
    including commands the user typed themselves."""
    term = Terminal(session)
    if new_only:
        text = await _in_thread(term.read_new, cursor="mcp")
    else:
        text = await _in_thread(term.read, lines)
    return text or "[nothing new]"


@mcp.tool(annotations=WRITES)
async def terminal_integrate(print_only: bool = False, force: bool = False, session: str | None = None) -> str:
    """Set up shell integration (invisible OSC 133 marks, bash / zsh) in the shared shell, so
    terminal_run no longer shows a printf marker on the user's screen. Types one setup line at the
    idle prompt and erases it again. print_only=True only returns the code for ~/.bashrc / ~/.zshrc.
    """
    if print_only:
        return si.script()
    return await _in_thread(Terminal(session).integrate, force=force)


@mcp.tool(annotations=READ_ONLY)
async def terminal_wait(
    timeout: float = 60, idle: float = 2.0, pattern: str | None = None, session: str | None = None
) -> str:
    """Wait for the pending terminal_run command to finish; or, if none is pending, until `pattern`
    (a regex) appears in new output, or until the terminal sits quietly at a prompt for `idle` seconds."""
    result = await _in_thread(Terminal(session).wait, timeout=timeout, idle=idle, pattern=pattern)
    return result.to_text() or "[no output]"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
