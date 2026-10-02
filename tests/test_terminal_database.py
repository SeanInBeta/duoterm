"""Verify the default TERM against a private database with no tmux-256color entry."""
import os
import shutil
import subprocess

import pytest


def test_screen_term_without_tmux_definition(term, tmp_path):
    if not shutil.which("tic") or not shutil.which("infocmp"):
        pytest.skip("requires terminfo tooling")
    if os.environ.get("DUOTERM_TEST_TERMINFO"):
        database = os.environ["DUOTERM_TEST_TERMINFO"]
    else:
        definition = subprocess.run(["infocmp", "-I", "screen-256color"], capture_output=True, text=True, check=True).stdout
        source = tmp_path / "screen.src"
        source.write_text(definition)
        database = tmp_path / "terminfo"
        subprocess.run(["tic", "-o", str(database), str(source)], check=True)
    env = {**os.environ, "TERMINFO": str(database), "TERMINFO_DIRS": str(database)}
    # -A selects only this database; environment-only lookup may fall back to system entries.
    assert subprocess.run(["infocmp", "-A", str(database), "screen-256color"], env=env, capture_output=True).returncode == 0
    assert subprocess.run(["infocmp", "-A", str(database), "tmux-256color"], env=env, capture_output=True).returncode != 0
    command = "infocmp -A '" + str(database) + "' \"$TERM\" >/dev/null"
    assert term.run(command).exit_code == 0
