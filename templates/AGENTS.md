<!-- Paste this into AGENTS.md / CLAUDE.md / your agent's system prompt. -->
## Shared terminal

I keep a terminal open that we share: a tmux session named `remote`, usually SSH'd into my server.
I watch it live and also type into it. Operate it only through `duoterm` (or the `terminal_*` MCP
tools if available); commands run on the remote server.

- `duoterm status`, then `duoterm read --new` to see what happened since you last looked (including what I typed).
- `duoterm run "<cmd>" [--timeout S]` runs one command at the idle prompt and returns output + `[exit N]`.
- Interactive programs / prompts: `duoterm screen`, `duoterm type "text" --enter`, `duoterm keys C-c Enter Escape ...`.
- `duoterm wait [--pattern RE] [--idle S]` for long jobs; exit code 124 = still running, 125 = duoterm error.
- If it says the terminal is not idle, look at `duoterm screen` and ask me. Never type secrets.
  Only use `--force` after I confirmed the exact command.
