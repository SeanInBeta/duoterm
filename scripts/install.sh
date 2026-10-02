#!/usr/bin/env bash
# Initialize the bundled runtime. Package/profile mutations require explicit flags.
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo "This Skill currently supports Linux/WSL only." >&2; exit 125; }
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PACKAGES=0
RECHECK=0
REPAIR_PATH=0
for arg in "$@"; do
    case "$arg" in
        --install-packages) INSTALL_PACKAGES=1 ;;
        --recheck) RECHECK=1 ;;
        --repair-path) REPAIR_PATH=1 ;;
        *) echo "Unknown option: $arg" >&2; exit 125 ;;
    esac
done
MISSING=()
command -v tmux >/dev/null || MISSING+=(tmux)
command -v ssh >/dev/null || MISSING+=(openssh-client)
command -v python3 >/dev/null || MISSING+=(python3)
command -v infocmp >/dev/null || MISSING+=(ncurses-bin)
if ! infocmp screen-256color >/dev/null 2>&1; then MISSING+=(ncurses-base); fi
if ! python3 -c 'import venv' >/dev/null 2>&1; then MISSING+=(python3-venv); fi
if ((${#MISSING[@]})); then
    if ((INSTALL_PACKAGES == 0)); then
        echo "Missing packages: ${MISSING[*]}. Review apt-get install, then authorize --install-packages." >&2
        exit 125
    fi
    command -v apt-get >/dev/null || { echo "Automatic dependency installation supports Ubuntu/Debian only." >&2; exit 125; }
    if ((EUID == 0)); then SUDO=(); else SUDO=(sudo -n); fi
    "${SUDO[@]}" apt-get update >&2
    "${SUDO[@]}" apt-get install -y "${MISSING[@]}" >&2
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3,10))' || { echo "Python >= 3.10 required." >&2; exit 125; }
OPTIONS=()
((RECHECK == 0)) || OPTIONS+=(--recheck)
((REPAIR_PATH == 0)) || OPTIONS+=(--repair-path)
export PYTHONPATH="$SCRIPTS/runtime${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m duoterm.setup --source "$SCRIPTS/runtime/duoterm" "${OPTIONS[@]}"
