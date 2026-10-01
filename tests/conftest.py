import os
import subprocess
import uuid

import pytest

from duoterm.core import Terminal

SHELL = "env PS1='$ ' HISTFILE=/dev/null bash --norc --noprofile"


@pytest.fixture
def term(tmp_path, monkeypatch):
    """A Terminal on an isolated tmux server running a plain local bash (stands in for ssh)."""
    socket = f"duoterm-test-{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("DUOTERM_TMUX_SOCKET", socket)
    monkeypatch.delenv("DUOTERM_SESSION", raising=False)
    monkeypatch.delenv("DUOTERM_PROMPT_RE", raising=False)
    t = Terminal(session="t", home=tmp_path / "home")
    t.start(command=SHELL)
    t._wait_for_prompt(5)
    yield t
    subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)


def human_types(term, text, enter=True):
    keys = [text] + (["Enter"] if enter else [])
    subprocess.run(["tmux", "-L", os.environ["DUOTERM_TMUX_SOCKET"], "send-keys", "-t", f"={term.session}:", *keys], check=True)
