import os
import shutil
import subprocess
import uuid

import pytest

from duoterm.core import Terminal

SHELL = "env PS1='$ ' HISTFILE=/dev/null bash --norc --noprofile"
SHELLS = {
    "bash": SHELL,
    # bash < 4.4 (no PS0, e.g. CentOS 7's 4.2) mode of the integration, forced on this bash.
    "bash-legacy": SHELL.replace("env ", "env DUOTERM_SI_LEGACY=1 ", 1),
    "zsh": "env PS1='%% ' HISTFILE=/dev/null zsh -f",
}


def _terminal(tmp_path, monkeypatch, command):
    socket = f"duoterm-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("DUOTERM_TMUX_SOCKET", socket)
    monkeypatch.delenv("DUOTERM_SESSION", raising=False)
    monkeypatch.delenv("DUOTERM_PROMPT_RE", raising=False)
    t = Terminal(session="t", home=tmp_path / "home")
    t.start(command=command)
    t._wait_for_prompt(5)
    return t, socket


@pytest.fixture
def term(tmp_path, monkeypatch):
    """A Terminal on an isolated tmux server running a plain local bash (stands in for ssh)."""
    t, socket = _terminal(tmp_path, monkeypatch, SHELL)
    yield t
    subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)


@pytest.fixture(params=sorted(SHELLS))
def shell_term(request, tmp_path, monkeypatch):
    """Like `term`, once per shell (zsh is skipped when it is not installed)."""
    binary = request.param.split("-")[0]
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} not installed")
    t, socket = _terminal(tmp_path, monkeypatch, SHELLS[request.param])
    t.shell = binary
    t.shell_variant = request.param
    yield t
    subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)


@pytest.fixture
def integrated(shell_term):
    """A bash/zsh terminal with duoterm's shell integration installed."""
    assert "integration active" in shell_term.integrate()
    return shell_term


def human_types(term, text, enter=True):
    keys = [text] + (["Enter"] if enter else [])
    subprocess.run(["tmux", "-L", os.environ["DUOTERM_TMUX_SOCKET"], "send-keys", "-t", f"={term.session}:", *keys], check=True)
