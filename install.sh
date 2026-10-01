#!/usr/bin/env bash
# Install duoterm inside WSL / Linux / macOS.
#   ./install.sh            install duoterm + duoterm-mcp into ~/.local/bin
#   ./install.sh --skills   also copy the shared-terminal skill into the agent skill folders that exist
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${DUOTERM_VENV:-$HOME/.local/share/duoterm/venv}"
BIN="$HOME/.local/bin"

need_pkg() {
    if command -v apt-get >/dev/null; then
        echo "-> installing $* (sudo apt-get)"; sudo apt-get update -qq && sudo apt-get install -y "$@"
    elif command -v brew >/dev/null; then
        echo "-> installing $* (brew)"; brew install "$@"
    else
        echo "!! please install: $*" >&2; exit 1
    fi
}

command -v tmux >/dev/null || need_pkg tmux
command -v ssh >/dev/null || need_pkg openssh-client
command -v python3 >/dev/null || need_pkg python3
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "!! Python >= 3.10 required" >&2; exit 1; }
python3 -m venv --help >/dev/null 2>&1 || need_pkg python3-venv

echo "-> creating venv $VENV"
python3 -m venv "$VENV" || { need_pkg python3-venv; python3 -m venv "$VENV"; }
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e "$REPO[mcp]"

mkdir -p "$BIN"
ln -sf "$VENV/bin/duoterm" "$BIN/duoterm"
ln -sf "$VENV/bin/duoterm-mcp" "$BIN/duoterm-mcp"
mkdir -p "$HOME/.duoterm" && chmod 700 "$HOME/.duoterm"
echo "-> installed: $BIN/duoterm, $BIN/duoterm-mcp"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "!! add to your shell rc: export PATH=\"$BIN:\$PATH\"";; esac

if [[ "${1:-}" == "--skills" ]]; then
    # Only into agents that are already set up on this machine.
    for dir in "$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.agents/skills" \
               "$HOME/.config/opencode/skills" "$HOME/.hermes/skills" "$HOME/.openclaw/skills"; do
        if [[ -d "$(dirname "$dir")" ]]; then
            mkdir -p "$dir" && cp -r "$REPO/skills/shared-terminal" "$dir/"
            echo "-> skill copied to $dir/shared-terminal"
        fi
    done
fi

cat <<'MSG'

Next:
  duoterm start myserver        # creates tmux session "remote" and runs: ssh myserver
  duoterm attach                # (in your second terminal) you now type in the shared session
Hook up your agent (pick what it supports):
  MCP:    claude mcp add duoterm -- duoterm-mcp      |  codex mcp add duoterm -- duoterm-mcp
  Skill:  ./install.sh --skills
  Plain:  paste templates/AGENTS.md into your AGENTS.md / CLAUDE.md / system prompt
MSG
