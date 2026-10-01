---
name: shared-terminal
description: Operate the user's shared terminal (a tmux session, usually SSH'd into a remote server) that the user watches and types into at the same time. Use when the user asks you to run something "on the server", "in the terminal", "over there", asks what just happened / what that error was in their terminal, or wants you to continue what they were doing in the SSH session.
---

# Shared terminal (duoterm)

The user has a terminal that both of you share. It is a tmux session (default name `remote`,
override with `-s NAME` or `$DUOTERM_SESSION`), usually running `ssh <server>`. The user sees
every keystroke you send, live, and may type into it as well. Everything runs **on the remote
server**, not on your local machine.

If MCP tools named `terminal_*` are available, prefer them; they map 1:1 to the commands below.
Otherwise use the `duoterm` CLI through your shell tool.

## Workflow

1. `duoterm status` - is the session there, idle at a prompt, anything still running?
2. `duoterm read --new` - what happened since you last looked, including what the user typed.
   Do this first whenever the user refers to "that", "the error", "what I just did".
3. `duoterm run "<command>"` - run one shell command at the idle prompt. Prints the output and
   `[exit N]`; the CLI's exit code is the command's exit code.
   - Long jobs: `duoterm run "<cmd>" --timeout 600`, or let it time out (exit 124, "still running")
     and later `duoterm wait --timeout 600`.
   - Interrupt: `duoterm keys C-c` (a following `duoterm wait` then reports `[exit 130]`).
4. Interactive programs (vim, less, top, `sudo` prompts, y/n questions, python/mysql REPLs):
   `duoterm screen` to look, then `duoterm type "text" --enter` and `duoterm keys Escape C-c Enter Up q ...`.
   Never wrap these in `duoterm run`.
5. Something the user started: `duoterm wait --pattern 'regex'` or `duoterm wait --idle 3`.

## Rules

- If `duoterm run` says the terminal is **not idle**, the user may be typing or a program is open:
  check `duoterm screen`, and ask the user instead of forcing your way in.
- Never type passwords, tokens or other secrets. Ask the user to type them into the terminal.
- `duoterm run` refuses obviously destructive commands (rm -rf /, mkfs, reboot, stopping sshd, ...).
  Only add `--force` after the user explicitly confirmed that exact command.
- One command per `duoterm run`; keep output small (`| tail -50`, `| head`, `grep`), output is capped
  to the last 200 lines (`--max-lines`).
- Do not `exit` the SSH session or start nested sessions unless asked.
- Use `--json` if you need structured output: `{"status","output","exit_code","message"}`.

Exit codes: command's own code for `run`/`wait`, 124 = still running, 125 = duoterm error
(no session, not idle, refused).
