import json
import os
import subprocess
import sys
import time

import pytest

from duoterm.core import DuotermError, Terminal, check_dangerous, clean_terminal_text, prettify

from .conftest import human_types


def test_run_returns_output_and_exit_code(term):
    r = term.run("echo hello; echo world")
    assert r.status == "done" and r.exit_code == 0
    assert r.output == "hello\nworld"
    assert term.run("false").exit_code == 1
    assert term.run("exit_code_test() { return 7; }; exit_code_test").exit_code == 7


@pytest.mark.parametrize(
    "command,expected",
    [
        ("echo 'a;b';", "a;b"),  # trailing ';' would be eaten by tmux
        ("echo x # comment", "x"),
        ("for i in 1 2; do\n  echo n$i\ndone", "n1\nn2"),
        ("echo 中文", "中文"),
        ("printf 'no newline'", "no newline"),
        ("printf '\\033[31mred\\033[0m\\n'", "red"),
    ],
)
def test_run_handles_awkward_commands(term, command, expected):
    r = term.run(command)
    assert r.exit_code == 0
    assert r.output == expected


def test_background_job(term):
    r = term.run("sleep 0.1 &")
    assert r.exit_code == 0 and r.output.startswith("[1] ")


def test_run_truncates_long_output(term):
    r = term.run("seq 1 500", max_lines=10)
    lines = r.output.split("\n")
    assert lines[0].startswith("[... 490 earlier lines omitted]")
    assert lines[1:] == [str(i) for i in range(491, 501)]


def test_timeout_then_wait(term):
    release = term.home / "release-timeout"
    r = term.run(f"while [ ! -f {release} ]; do sleep 0.05; done; echo late", timeout=0.3)
    assert r.status == "running" and r.process_exit == 124
    with pytest.raises(DuotermError, match="still running"):
        term.run("pwd")
    release.touch()
    w = term.wait(timeout=10)
    assert w.status == "done" and w.exit_code == 0 and w.output == "late"
    assert term.run("echo next").output == "next"


def test_refuses_when_not_idle(term):
    human_types(term, "sleep 30")
    time.sleep(0.2)
    with pytest.raises(DuotermError, match="not at an idle shell prompt"):
        term.run("pwd")
    term.keys("C-c")
    assert term.wait(timeout=10, idle=0.3).status == "done"
    assert term.run("echo ok").output == "ok"


def test_refuses_when_user_is_half_way_typing(term):
    human_types(term, "echo half", enter=False)
    time.sleep(0.2)
    assert term.is_idle() == (False, "$ echo half")
    with pytest.raises(DuotermError):
        term.run("pwd")


def test_dangerous_commands_need_force(term):
    with pytest.raises(DuotermError, match="dangerous"):
        term.run("rm -rf /")
    assert check_dangerous("rm -rf ./build") is None
    assert check_dangerous("sudo reboot") is not None
    assert check_dangerous("dd if=x.img of=/dev/sdb") is not None
    assert check_dangerous("ls -la /") is None


def test_read_new_sees_what_the_human_did(term):
    term.read_new()  # move cursor to now
    human_types(term, "echo typed-by-human")
    time.sleep(0.3)
    new = term.read_new()
    assert "echo typed-by-human" in new and "\ntyped-by-human" in new
    assert term.read_new().strip() in ("", "$")
    term.run("echo from-agent")
    new = term.read_new()
    assert "echo from-agent\nfrom-agent\n[exit 0]" in new
    assert "__RT_" not in new


def test_read_and_screen(term):
    term.run("echo visible-line")
    assert "visible-line" in term.read(20)
    assert "__RT_" not in term.read(20)
    assert "[cursor row" in term.screen()


def test_interactive_program_with_type_and_keys(term):
    term.type_text("cat", enter=True)
    time.sleep(0.2)
    assert term.is_idle()[0] is False
    term.type_text("echo-me", enter=True)
    time.sleep(0.2)
    assert term.screen().count("echo-me") == 2
    term.keys("C-d")
    term._wait_for_prompt(5)
    assert term.is_idle()[0]


def test_wait_for_pattern(term):
    human_types(term, "sleep 0.5; echo READY-NOW")
    r = term.wait(timeout=10, pattern=r"^READY-NOW")
    assert r.status == "done" and "READY-NOW" in r.output


def test_status_bar_is_restored(term):
    from duoterm import tmux as tm

    release = term.home / "release-status"
    term.run(f"while [ ! -f {release} ]; do sleep 0.05; done", timeout=0.1)
    assert "AGENT CMD STILL RUNNING" in tm.get_option(term.session, "status-right")
    release.touch()
    term.wait(timeout=10)
    assert tm.get_option(term.session, "status-right") == ""


def test_log_and_home_are_private(term):
    assert oct(term.home.stat().st_mode & 0o777) == "0o700"
    assert oct(term.log_path.stat().st_mode & 0o777) == "0o600"


def test_context_for_hooks(term):
    term.run("echo activity")
    assert term.context().startswith('<shared-terminal session="t">')
    assert term.context() == ""
    assert Terminal(session="missing", home=term.home).context() == ""


def test_cli_json_and_exit_codes(term):
    env = {**os.environ, "DUOTERM_HOME": str(term.home), "DUOTERM_SESSION": term.session}
    run = lambda *a: subprocess.run([sys.executable, "-m", "duoterm.cli", *a], capture_output=True, text=True, env=env)
    p = run("--json", "run", "echo cli; exit_fn() { return 3; }; exit_fn")
    assert p.returncode == 3
    assert json.loads(p.stdout)["output"] == "cli"
    p = run("run", "rm -rf ~")
    assert p.returncode == 125 and "dangerous" in p.stderr
    assert run("-s", "nope", "status").returncode == 125


def test_clean_terminal_text():
    raw = "\x1b]0;title\x07$ ls\r\nab\x08c\r\n\x1b[1;32mgreen\x1b[0m\r\n10%\r50%\r100%\r\n"
    assert clean_terminal_text(raw) == "$ ls\nac\ngreen\n100%\n"
    assert prettify("$ pwd; printf '\\n__RT_%s_%d__\\n' 0123abcd $?\n/root\n\n__RT_0123abcd_0__\n$ ") == "$ pwd\n/root\n[exit 0]\n$ "


def test_interrupted_command_is_detected(term):
    r = term.run("sleep 30", timeout=0.3)
    assert r.status == "running"
    term.keys("C-c")
    w = term.wait(timeout=5)
    assert w.status == "done" and w.exit_code == 130 and "interrupted" in w.message
    assert term.run("echo after").output == "after"


def test_interrupted_command_does_not_block_next_run(term):
    term.run("sleep 30", timeout=0.3)
    term.keys("C-c")
    term._wait_for_prompt(5)
    assert term.run("echo next").output == "next"


def test_marker_found_even_if_output_ends_like_a_prompt(term):
    r = term.run("printf 'cost $'; sleep 0.5")
    assert r.exit_code == 0 and r.output == "cost $"


def test_start_does_not_nest_ssh_into_existing_session(term):
    msg = term.start("somehost")
    assert "ssh not re-sent" in msg
    assert "ssh somehost" not in term.read(10)


def test_idle_check_survives_wrapped_lines(term):
    long_word = "x" * 450  # wider than the 200-column pane: wraps over three rows
    assert term.run(f"echo {long_word}").output == long_word
    assert term.is_idle() == (True, "$")
    assert term.run("echo after-wrap").output == "after-wrap"


def test_shared_pane_uses_a_widely_known_term(term):
    # tmux-256color is missing on older servers (CentOS 7), where readline then hides the prompt.
    assert term.run("echo $TERM").output == "screen-256color"


@pytest.mark.parametrize("value", ["xterm-256color", ""])
def test_term_can_be_overridden(tmp_path, monkeypatch, value):
    from duoterm import tmux as tm

    from .conftest import SHELL, _terminal

    monkeypatch.setenv("DUOTERM_TERM", value)
    t, socket = _terminal(tmp_path, monkeypatch, SHELL)
    try:
        expected = value or tm.tmux("show-options", "-sv", "default-terminal").strip()  # "" keeps tmux's default
        assert t.run("echo $TERM").output == expected
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)
