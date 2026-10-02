import os
import shutil
import shlex
import subprocess
import uuid
from pathlib import Path

import pytest

from duoterm.core import Terminal

SHELL = "env PS1='$ ' HISTFILE=/dev/null " + shlex.quote(os.environ.get("DUOTERM_TEST_BASH", "bash")) + " --norc --noprofile"
SHELLS = {
    "bash": SHELL,
    # bash < 4.4 (no PS0, e.g. CentOS 7's 4.2) mode of the integration, forced on this bash.
    "bash-legacy": SHELL.replace("env ", "env DUOTERM_SI_LEGACY=1 ", 1),
    "zsh": "env PS1='%% ' HISTFILE=/dev/null zsh -f",
}


@pytest.fixture(autouse=True)
def runtime_import_path(monkeypatch):
    # pytest's pythonpath setting does not propagate to subprocess CLI checks.
    runtime = str(Path(__file__).resolve().parents[1] / "scripts" / "runtime")
    monkeypatch.setenv("PYTHONPATH", runtime + os.pathsep + os.environ.get("PYTHONPATH", ""))


def _terminal(tmp_path, monkeypatch, command):
    if shutil.which("tmux") is None:
        pytest.skip("tmux runtime tests require Linux/WSL")
    socket = f"duoterm-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("DUOTERM_TMUX_SOCKET", socket)
    monkeypatch.setenv("DUOTERM_TMUX_CONFIG", "/dev/null")
    monkeypatch.delenv("DUOTERM_SESSION", raising=False)
    monkeypatch.delenv("DUOTERM_PROMPT_RE", raising=False)
    # Tests opt in to automatic shell integration explicitly; by default they cover the printf marker.
    monkeypatch.setenv("DUOTERM_AUTO_INTEGRATE", "0")
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
    message = shell_term.integrate()
    assert "integration active" in message, (
        message + "\n" + shell_term.screen() + "\n" + repr(shell_term.log_path.read_bytes()[-3500:])
    )
    return shell_term


def human_types(term, text, enter=True):
    keys = [text] + (["Enter"] if enter else [])
    subprocess.run(["tmux", "-L", os.environ["DUOTERM_TMUX_SOCKET"], "send-keys", "-t", f"={term.session}:", *keys], check=True)
