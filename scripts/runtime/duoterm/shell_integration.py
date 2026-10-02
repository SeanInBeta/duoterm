"""Shell integration: invisible OSC 133 marks that tell duoterm where a command ends.

With it installed in the shared shell, `run` sends just the command and reads the exit code
from `ESC ] 133 ; D ; <exit> BEL`, which the terminal never displays but pipe-pane logs.
Same idea as the FinalTerm / iTerm2 / VS Code shell integrations.
"""

from __future__ import annotations

# D = previous command finished (with its exit code), A = prompt starts, C = command starts.
# The hook goes first so it sees the real $?, and hands the same $? back to whatever runs
# after it. Not exported: a nested shell (bash, sudo -i, ssh) must not look integrated.
# bash < 4.4 has no PS0 to print C, so it marks the end of the prompt instead (B, appended
# to PS1 after every PROMPT_COMMAND in case something rewrote PS1): duoterm then knows the
# shell sits at its own prompt when nothing was printed after the last B. The mark comes from
# a non-exported variable, so a nested shell that inherits an exported PS1 prints no B.
# DUOTERM_SI_LEGACY=1 forces that bash < 4.4 mode on newer bash (used by the tests).
SCRIPT = r"""
# duoterm shell integration: invisible OSC 133 marks so duoterm needs no visible marker.
# bash or zsh (elsewhere it does nothing). Put it at the END of ~/.bashrc / ~/.zshrc.
if [ -z "${__duoterm_si-}" ]; then
  __duoterm_si=1
  __duoterm_prompt() { local s=$?; printf '\033]133;D;%s\007\033]133;A\007' "$s"; return $s; }
  if [ -n "${ZSH_VERSION-}" ]; then
    __duoterm_preexec() { printf '\033]133;C\007'; }
    precmd_functions=(__duoterm_prompt $precmd_functions)
    preexec_functions=($preexec_functions __duoterm_preexec)
  elif [ -n "${BASH_VERSION-}" ]; then
    __duoterm_end=
    if [ "$((BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1]))" -ge 404 ] && [ -z "${DUOTERM_SI_LEGACY-}" ]; then
      PS0="${PS0-}"'\e]133;C\a'
    else
      __duoterm_b=$'\e]133;B\a'
      __duoterm_ps1() { local s=$?; case "$PS1" in *__duoterm_b*) ;; *) ! shopt -q promptvars || PS1="$PS1"'\[${__duoterm_b-}\]' ;; esac; return $s; }
      __duoterm_end=__duoterm_ps1
    fi
    if [[ "$(declare -p PROMPT_COMMAND 2>/dev/null)" == "declare -a"* ]]; then
      PROMPT_COMMAND=(__duoterm_prompt "${PROMPT_COMMAND[@]}" $__duoterm_end)
    else
      PROMPT_COMMAND="__duoterm_prompt${PROMPT_COMMAND:+$'\n'$PROMPT_COMMAND}${__duoterm_end:+$'\n'$__duoterm_end}"
    fi
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
