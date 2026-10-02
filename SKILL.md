---
name: duoterm
description: Set up and operate terminals shared with the user through tmux, including multiple WSL or SSH terminals from a Windows PowerShell agent. Use when the user enables duoterm, asks to view a shared terminal, or names a shared terminal for an action. Once enabled, follow its routing rules throughout this conversation until the user exits or changes execution location.
---

# duoterm

Operate shared tmux sessions through the bundled CLI. The user opens visible WSL windows and manually runs `start` and `attach`. Keep existing work intact. No MCP, hooks or global agent configuration is required.

## Activate in each new conversation

1. Read user-private `~/.duoterm/setup.json` on the agent's operating system. Only JSON `complete: true` is authoritative; never mark completion yourself based on a checked Markdown box. The Windows record identifies the WSL distribution, Linux user and runtime. Do not persist conversation routing or aliases in this record.
2. Read [references/setup.md](references/setup.md) for the initializer entrypoint. Call it on activation: its cached path checks the saved completion/source fingerprint and skips environment diagnostics and installation entirely. First/incomplete/changed setup resumes initialization; explicit recheck reruns verification. For a later failure, repair that specific issue using [references/troubleshooting.md](references/troubleshooting.md).
3. Discover sessions with `duoterm list --json`. Windows uses the absolute path to this skill's `scripts/invoke.ps1` for **all** CLI calls, e.g. `& 'C:/path/to/duoterm/scripts/invoke.ps1' list --json`. Pass command text as one PowerShell string argument. WSL/Linux uses the installed CLI. Never concatenate user commands into `wsl.exe ... bash -c`.
4. Show session names, attachment, idle/busy and connection status. Names A/B are identifiers. For default `remote`, ask what the user calls it (e.g. Duoterm 1) and remember that alias only in this conversation. Do not rename/recreate sessions. Unrelated tmux sessions and untagged pre-upgrade sessions are not automatically adopted; adopt only a user-identified, confirmed session via `duoterm -s NAME start --adopt`.
5. If sessions exist, show what was found and invite the user to add more before continuing. A subsequent explicit operation is enough to proceed without another approval ritual. If none exist, provide the two-line single/multiple-window instructions in setup.md. Never open/attach the user's windows. `attach` alone cannot create a session.
6. After the user opens/adds windows, rerun discovery and check each selected session. Unattached sessions need attachment; authentication prompts need user input. Busy sessions are readable but cannot accept a new shell command. Connection hints are not proof of server identity: inspect status/screen and never call a disconnected local shell the remote server. Confirm readiness only from current evidence.

## Conversation routing

After readiness, remember in the **current conversation**: duoterm enabled, confirmed alias-to-session map, and execution location (shared or local). Keep this small summary through compaction. A new conversation starts without routing even if the machine is initialized. Never write a global agent instruction or persistent routing flag.

- One confirmed session: ordinary execution requests default to it.
- Multiple sessions: use the user's explicit name/alias. Ask if absent or ambiguous, never guess the last-used session. For A and B, perform and label each operation separately.
- "Use current PowerShell/local terminal" switches to local until the user explicitly selects a shared terminal again. "Only this time locally" overrides one task, then restores the previous mode. "Exit shared mode" disables routing until reenabled.
- Setup, discovery and forwarding are local control operations. User work runs at the chosen location. For shared-environment file edits use commands there; do not edit a similarly named local checkout.
- Fetch fresh output for "the error" or "what I just did". Reading is tool-driven, not continuous background monitoring. No prompt hook is installed.

## Operate the selected session

Always include `-s ACTUAL_NAME`. First `status`, then `read --new` / `screen`, then act. Never trust an old discovery snapshot before a write. Use a stable unique `--cursor` per conversation.

```bash
duoterm -s A status --json
duoterm -s A read --new --cursor conversation-id
duoterm -s A run 'df -h'
duoterm -s A screen
duoterm -s A wait --timeout 60
```

- `run` executes at an idle prompt and returns output/exit code. OSC 133 integration is automatic in bash/zsh, including legacy Bash. Do not require users to configure integration or change remote rc files. Unsupported integration uses the visible marker fallback.
- Exit 124 means still running: use `wait`, never resubmit. Interrupt with `keys C-c` only when requested, then `wait` for the result.
- Interactive programs use `screen`, `type TEXT --enter`, and `keys`, not `run`. Never type passwords, tokens or host-key approvals. The user handles them in the attached window.
- Do not force busy/partially typed terminals. `--force` also bypasses dangerous-command checks and needs explicit authorization for that exact operation.
- Report the session label and observed exit code. Exit 125 is a duoterm error, not a remote result. Limit output using `--max-lines` or selective shell commands.

The CLI implements observation/execution. Conversation rules are followed by the agent, not enforced as a global host mode.
