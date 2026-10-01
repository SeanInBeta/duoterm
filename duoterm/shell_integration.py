"""Shell integration: invisible OSC 133 marks that tell duoterm where a command ends.

With it installed in the shared shell, `run` sends just the command and reads the exit code
from `ESC ] 133 ; D ; <exit> BEL`, which the terminal never displays but pipe-pane logs.
Same idea as the FinalTerm / iTerm2 / VS Code shell integrations.
"""

from __future__ import annotations

# D = previous command finished (with its exit code), A = prompt starts, C = command starts.
# The hook goes first so it sees the real $?, and hands the same $? back to whatever runs
# after it. Not exported: a nested shell (bash, sudo -i, ssh) must not look integrated.
SCRIPT = r"""
# duoterm shell integration: invisible OSC 133 marks so duoterm needs no visible marker.
# bash >= 4.4 or zsh (elsewhere it does nothing). Put it at the END of ~/.bashrc / ~/.zshrc.
if [ -z "${__duoterm_si-}" ]; then
  __duoterm_si=1
  __duoterm_prompt() { local s=$?; printf '\033]133;D;%s\007\033]133;A\007' "$s"; return $s; }
  if [ -n "${ZSH_VERSION-}" ]; then
    __duoterm_preexec() { printf '\033]133;C\007'; }
    precmd_functions=(__duoterm_prompt $precmd_functions)
    preexec_functions=($preexec_functions __duoterm_preexec)
  elif [ "$((${BASH_VERSINFO[0]:-0} * 100 + ${BASH_VERSINFO[1]:-0}))" -ge 404 ]; then
    if [[ "$(declare -p PROMPT_COMMAND 2>/dev/null)" == "declare -a"* ]]; then
      PROMPT_COMMAND=(__duoterm_prompt "${PROMPT_COMMAND[@]}")
    else
      PROMPT_COMMAND="__duoterm_prompt${PROMPT_COMMAND:+$'\n'$PROMPT_COMMAND}"
    fi
    PS0="${PS0-}"'\e]133;C\a'
  fi
fi
"""

_JOIN_WITH_SPACE = ("then", "else", "do", "{", "&&", "||", "|")


def script() -> str:
    """The setup code, readable, for ~/.bashrc or ~/.zshrc."""
    return SCRIPT.strip() + "\n"


def one_line() -> str:
    """The same code on one line, to type into a live shell."""
    lines = [ln.strip() for ln in SCRIPT.strip().splitlines() if ln.strip() and not ln.strip().startswith("#")]
    out = lines[0]
    for line in lines[1:]:
        out += (" " if out.endswith(_JOIN_WITH_SPACE) else "; ") + line
    return out
