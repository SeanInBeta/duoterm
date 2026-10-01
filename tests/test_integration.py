"""Shell integration (OSC 133): invisible completion marks instead of the visible printf marker."""

import json
import os
import subprocess
import sys
import time

import pytest

from duoterm import shell_integration as si
from duoterm.core import DuotermError, complete_prefix, render_marks

from .conftest import SHELLS, human_types

VISIBLE_MARKER_BITS = ("__RT_", "printf '\\n", "133;", "\x1b", "\x07", "__duoterm")


def assert_clean(text):
    for bit in VISIBLE_MARKER_BITS:
        assert bit not in text, f"{bit!r} in {text!r}"


def test_integrated_run_returns_output_and_exit_code(integrated):
    assert integrated.status()["shell_integration"] is True
    r = integrated.run("echo hello; echo world")
    assert (r.status, r.exit_code, r.output) == ("done", 0, "hello\nworld")
    assert integrated.run("ls /nonexistent-dir").exit_code == 2
    assert integrated.run("exit_code_test() { return 7; }; exit_code_test").exit_code == 7
    assert integrated.run("false").exit_code == 1


@pytest.mark.parametrize(
    "command,expected",
    [
        ("echo 'a;b';", "a;b"),
        ("for i in 1 2; do\n  echo n$i\ndone", "n1\nn2"),
        ("echo 中文", "中文"),
        ("printf 'no newline'", "no newline"),
        ("printf '\\033[31mred\\033[0m\\n'", "red"),
        ("printf 'cost $'; sleep 0.5", "cost $"),
    ],
)
def test_integrated_run_handles_awkward_commands(integrated, command, expected):
    r = integrated.run(command)
    assert r.exit_code == 0
    assert r.output == expected


def test_screen_shows_only_the_command_and_its_output(integrated):
    integrated.run("echo first-cmd")
    integrated.run("ls /nonexistent-dir")
    screen = integrated.screen()
    assert_clean(screen)
    assert_clean(integrated.read(50))
    # The integrate line was erased again: the screen starts with the agent's first command.
    rows = [row for row in screen.split("\n") if row.strip()]
    assert rows[0].endswith(" echo first-cmd")
    assert rows[1] == "first-cmd"


def test_falls_back_to_printf_marker_without_integration(shell_term):
    assert shell_term.status()["shell_integration"] is False
    r = shell_term.run("echo plain; false")
    assert (r.output, r.exit_code) == ("plain", 1)
    assert "__RT_%s_%d__" in shell_term.screen()  # the visible marker was used


def test_nested_shell_falls_back_until_it_exits(integrated):
    human_types(integrated, SHELLS[integrated.shell])  # e.g. sudo -i / a subshell / ssh elsewhere
    integrated._wait_for_prompt(5)
    time.sleep(0.3)
    assert integrated.status()["shell_integration"] is False
    r = integrated.run("echo nested; false")
    assert (r.output, r.exit_code) == ("nested", 1)
    assert "__RT_%s_%d__" in integrated.screen()
    human_types(integrated, "exit")
    time.sleep(0.5)
    assert integrated.status()["shell_integration"] is True
    assert integrated.run("echo back").output == "back"
    assert "echo back; printf" not in integrated.read(5)


def test_integration_is_idempotent(integrated, tmp_path):
    assert "already active" in integrated.integrate()
    script = tmp_path / "si.sh"
    script.write_text(si.script())
    assert integrated.run(f". {script}; . {script}").exit_code == 0
    hooks = "$PROMPT_COMMAND" if integrated.shell == "bash" else "${(F)precmd_functions}"
    r = integrated.run(f'printf "%s\\n" "{hooks}" | grep -c __duoterm_prompt')
    assert r.output == "1"
    r = integrated.run("echo still-ok; false")
    assert (r.output, r.exit_code) == ("still-ok", 1)


def test_keeps_existing_prompt_command_and_its_exit_status(term, tmp_path):
    seen = tmp_path / "seen"
    term.run(f"PROMPT_COMMAND='echo \"$? $PWD\" > {seen}'")
    assert "integration active" in term.integrate()
    assert term.run("cd /tmp; false").exit_code == 1
    time.sleep(0.2)
    assert seen.read_text() == "1 /tmp\n"  # the user's hook still runs and still sees the real $?


def test_keeps_array_prompt_command(term, tmp_path):
    a0, a1 = tmp_path / "a0", tmp_path / "a1"
    term.run(f"PROMPT_COMMAND=('echo $? > {a0}' 'echo ran > {a1}')")
    assert "integration active" in term.integrate()
    assert term.run("(exit 4)").exit_code == 4
    time.sleep(0.2)
    assert (a0.read_text(), a1.read_text()) == ("4\n", "ran\n")
    assert term.run("declare -p PROMPT_COMMAND").output.startswith('declare -a PROMPT_COMMAND=([0]="__duoterm_prompt"')


def test_keeps_zsh_precmd_hooks(integrated, tmp_path):
    if integrated.shell != "zsh":
        pytest.skip("zsh only")
    seen = tmp_path / "seen"
    integrated.run(f"user_hook() {{ echo $? > {seen} }}; precmd_functions+=(user_hook)")
    assert integrated.run("(exit 5)").exit_code == 5
    time.sleep(0.2)
    assert seen.read_text() == "5\n"


@pytest.mark.parametrize(
    "setup,last_line",
    [
        # conda activate prepends "(env) " to whatever PS1 is, before or after integrating.
        ("PS1=\"(common) $PS1\"", "(other) (common) $"),
        ("PS1='\\[\\e[1;32m\\]\\u@\\h\\[\\e[0m\\] \\w\\n$ '", "$"),  # colours + two-line prompt
    ],
)
def test_custom_prompts_keep_working(term, setup, last_line):
    term.run(setup)
    assert "integration active" in term.integrate()
    assert term.run("PS1=\"(other) $PS1\"").exit_code == 0  # conda activate after integrating
    r = term.run("echo in-env; false")
    assert (r.output, r.exit_code) == ("in-env", 1)
    assert term.read(3).split("\n")[-1].rstrip() == last_line
    assert_clean(term.read(30))


def test_timeout_then_wait(integrated):
    from duoterm import tmux as tm

    r = integrated.run("sleep 1.5; echo late", timeout=0.3)
    assert r.status == "running" and r.process_exit == 124
    assert "AGENT CMD STILL RUNNING" in tm.get_option(integrated.session, "status-right")
    with pytest.raises(DuotermError, match="still running"):
        integrated.run("pwd")
    w = integrated.wait(timeout=10)
    assert (w.status, w.exit_code, w.output) == ("done", 0, "late")
    assert tm.get_option(integrated.session, "status-right") == ""
    assert integrated.run("echo next").output == "next"


def test_ctrl_c_gives_exit_130(integrated):
    r = integrated.run("sleep 30", timeout=0.3)
    assert r.status == "running"
    integrated.keys("C-c")
    w = integrated.wait(timeout=5)
    assert (w.status, w.exit_code) == ("done", 130)
    assert integrated.run("echo after").output == "after"


def test_read_new_and_context_have_no_osc_residue(integrated):
    integrated.read_new()
    integrated.run("echo from-agent")
    human_types(integrated, "echo from-human; (exit 3)")
    time.sleep(0.5)
    new = integrated.read_new()
    assert_clean(new)
    assert "echo from-agent\nfrom-agent\n[exit 0]" in new
    assert "from-human\n[exit 3]" in new
    integrated.run("echo more")
    ctx = integrated.context()
    assert ctx.startswith('<shared-terminal session="t">') and "more" in ctx
    assert_clean(ctx)


def test_read_new_holds_back_half_written_marks(integrated):
    integrated.read_new()
    with open(integrated.log_path, "ab") as fh:
        fh.write(b"partial-line\x1b]133;D")
    first = integrated.read_new()
    assert "partial-line" in first and "133" not in first
    with open(integrated.log_path, "ab") as fh:
        fh.write(b";0\x07after\n")
    rest = integrated.read_new()
    assert "after" in rest
    assert_clean(rest)


def test_lost_integration_falls_back_and_still_gets_exit_code(term):
    # A shell that is not integrated but where the log's last mark is a prompt mark, as after
    # ssh to an integrated server drops back to the local shell.
    human_types(term, r"printf '\033]133;A\007'")
    time.sleep(0.3)
    assert term.status()["shell_integration"] is True
    r = term.run("echo lost; false", timeout=10)
    assert (r.output, r.exit_code) == ("lost", 1)
    assert "no shell integration" in r.message
    assert term.status()["shell_integration"] is False
    assert term.run("echo next").output == "next"


def test_integrate_in_unsupported_shell_keeps_fallback(tmp_path, monkeypatch):
    from .conftest import _terminal

    if subprocess.run(["sh", "-c", "[ -n \"$BASH_VERSION$ZSH_VERSION\" ]"]).returncode == 0:
        pytest.skip("sh is bash/zsh here")
    t, socket = _terminal(tmp_path, monkeypatch, "env PS1='$ ' sh")
    try:
        assert "no OSC 133 prompt mark appeared" in t.integrate(timeout=2)
        assert t.status()["shell_integration"] is False
        assert t.run("echo still-works").output == "still-works"
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)


def test_cli_integrate_and_status(term):
    env = {**os.environ, "DUOTERM_HOME": str(term.home), "DUOTERM_SESSION": term.session}
    run = lambda *a: subprocess.run([sys.executable, "-m", "duoterm.cli", *a], capture_output=True, text=True, env=env)
    assert json.loads(run("--json", "status").stdout)["shell_integration"] is False
    p = run("integrate")
    assert p.returncode == 0 and "integration active" in p.stdout
    assert "shell_integration: True" in run("status").stdout
    p = run("--json", "run", "echo cli; exit_fn() { return 3; }; exit_fn")
    assert p.returncode == 3 and json.loads(p.stdout)["output"] == "cli"
    p = run("integrate", "--print")
    assert p.stdout == si.script()


def test_script_is_valid_and_one_line_matches(tmp_path):
    for shell in ("bash", "zsh"):
        if not subprocess.run(["sh", "-c", f"command -v {shell}"], capture_output=True).returncode == 0:
            continue
        for code in (si.script(), si.one_line()):
            assert subprocess.run([shell, "-n", "-c", code]).returncode == 0
    assert "\n" not in si.one_line()


def test_mark_helpers():
    raw = b"$ ls\r\n\x1b]133;C\x07out\r\n\x1b]133;D;2\x07\x1b]133;A\x07$ \r\n\x1b]133;D;2\x07\x1b]133;A\x07$ "
    # Only a D that ends a command (after C) becomes [exit N]; an empty Enter's D vanishes.
    assert render_marks(raw) == b"$ ls\r\nout\r\n\n[exit 2]\n$ \r\n$ "
    assert complete_prefix(b"ok\x1b]133;D;0") == 2
    assert complete_prefix(b"ok\x1b]0;title\x1b") == 2
    assert complete_prefix(b"ok\x1b]133;A\x07") == 10
    assert complete_prefix("中".encode()[:2]) == 0


def test_offsets_inside_sequences_are_moved_past_them(tmp_path):
    from duoterm.core import Terminal

    t = Terminal(session="x", home=tmp_path)
    data = b"ab\x1b]133;D;0\x07cd" + "中".encode() + b"ef\x1b[31mgh"
    t.log_path.write_bytes(data)
    assert [t._align(o) for o in (2, 3, 11, 12, 15, 16, 17, 20, 24)] == [2, 12, 12, 12, 17, 17, 17, 24, 24]
    assert t._log_since(5) == ("cd中efgh", len(data))
