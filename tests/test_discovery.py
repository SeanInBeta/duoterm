import json
import os
import subprocess
import sys
import time

import pytest

from duoterm.core import Terminal, DuotermError
from duoterm import tmux as tm
from .conftest import SHELL


def test_discovers_three_managed_sessions_only(term):
    terminals = [term]
    for name in ("A", "B"):
        t = Terminal(name, home=term.home)
        t.start(command=SHELL)
        t._wait_for_prompt(5)
        terminals.append(t)
    tm.tmux("new-session", "-d", "-s", "unrelated", "sleep 30")
    for t in terminals:
        assert t.run(f"echo only-{t.session}").output == f"only-{t.session}"
    records = term.list_sessions()
    assert {r["session"] for r in records} == {"t", "A", "B"}
    assert all(not r["attached"] and r["attached_clients"] == 0 for r in records)
    for t in terminals:
        text = t.read_new(cursor="conversation-1")
        assert f"only-{t.session}" in text
        assert all(f"only-{other.session}" not in text for other in terminals if other is not t)
        assert t.read_new(cursor="conversation-1").strip() in ("", "$")
        assert f"only-{t.session}" in t.read_new(cursor="conversation-2")


def test_legacy_session_requires_explicit_adoption(term):
    tm.unset_option(term.session, "@duoterm")
    assert term.list_sessions() == []
    with pytest.raises(DuotermError, match="--adopt"):
        term.start()
    term.start(adopt=True)
    assert [r["session"] for r in term.list_sessions()] == [term.session]
    assert term.run("echo preserved").output == "preserved"


def test_busy_and_disconnected_states(term):
    release = term.home / "release-discovery"
    command = f"while [ ! -f {release} ]; do sleep 0.05; done"
    term.run(command, timeout=0.1)
    snapshot = term.list_sessions()[0]
    assert not snapshot["idle_at_prompt"] and snapshot["pending_agent_command"] == command
    release.touch()
    term.wait(timeout=5)
    tm.set_option(term.session, "@duoterm_target", "somehost")
    assert term.status()["connection_state"] == "disconnected"


def test_attached_client_is_discovered(term):
    # A real TTY client attaches to the isolated test server, then detaches.
    import pty
    master, slave = pty.openpty()
    env = {**os.environ, "TERM": "xterm-256color"}
    client = subprocess.Popen(tm._base_cmd() + ["attach", "-t", term.session],
                              stdin=slave, stdout=slave, stderr=slave, env=env)
    try:
        for _ in range(30):
            snapshot = term.list_sessions()[0]
            if snapshot["attached"]:
                break
            time.sleep(0.1)
        assert snapshot["attached_clients"] == 1
    finally:
        tm.tmux("detach-client", "-s", term.session, check=False)
        client.wait(timeout=5)
        os.close(master)
        os.close(slave)


def test_list_json_flag_after_subcommand(term):
    result = subprocess.run([sys.executable, "-m", "duoterm.cli", "list", "--json"],
                            capture_output=True, text=True, env={**os.environ, "DUOTERM_HOME": str(term.home)})
    assert result.returncode == 0
    assert json.loads(result.stdout)["sessions"][0]["session"] == "t"


@pytest.mark.parametrize("name", ["../x", "a:b", "a/b", "two words"])
def test_session_names_cannot_escape_state_directory(name):
    with pytest.raises(DuotermError):
        Terminal(name)


def test_invalid_cli_session_is_structured_error():
    result = subprocess.run([sys.executable, "-m", "duoterm.cli", "-s", "../x", "status", "--json"],
                            capture_output=True, text=True)
    assert result.returncode == 125
    assert json.loads(result.stdout)["status"] == "error"
