import json
from pathlib import Path
import shutil
import subprocess

import pytest

from duoterm import setup


def test_record_unchecked_until_success(tmp_path):
    setup.save_record(tmp_path, {"complete": False, "stage": "blocked", "error": "needs user input"})
    assert "- [ ] 首次环境检查已完成" in (tmp_path / "setup.md").read_text()
    assert not setup.load_record(tmp_path)["complete"]
    setup.save_record(tmp_path, {"complete": True, "stage": "ready"})
    assert "- [x] 首次环境检查已完成" in (tmp_path / "setup.md").read_text()


def test_corrupt_record_does_not_skip_setup(tmp_path):
    (tmp_path / "setup.json").write_text("{broken")
    assert setup.load_record(tmp_path) == {}
    (tmp_path / "setup.json").write_text("[]")
    assert setup.load_record(tmp_path) == {}


def test_completed_setup_skips_checks_and_writes(tmp_path, monkeypatch):
    source = Path(setup.__file__).parent
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "entry.py").write_text("pass")
    python = tmp_path / "python"
    python.touch()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "duoterm").touch()
    setup.save_record(tmp_path, {"complete": True, "source_hash": setup.source_hash(source),
                                "runtime_path": str(runtime), "python": str(python)})
    before = (tmp_path / "setup.json").read_bytes()
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: pytest.fail("second activation ran diagnostics"))
    result = setup.initialize(source, tmp_path, tmp_path / "install", binaries)
    assert result["complete"] and result["skipped"]
    assert (tmp_path / "setup.json").read_bytes() == before


def test_partial_install_failure_remains_unchecked(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.venv.EnvBuilder, "create", lambda *a: (_ for _ in ()).throw(OSError("interrupted")))
    source = Path(setup.__file__).parent
    result = setup.initialize(source, tmp_path / "state", tmp_path / "install", tmp_path / "bin")
    assert not result["complete"] and "interrupted" in result["error"]
    assert not setup.load_record(tmp_path / "state")["complete"]


def test_initialize_recheck_and_detached_runtime(tmp_path, monkeypatch):
    if shutil.which("tmux") is None:
        pytest.skip("needs tmux")
    source = tmp_path / "download" / "duoterm"
    shutil.copytree(Path(setup.__file__).parent, source, ignore=shutil.ignore_patterns("__pycache__"))
    binaries = tmp_path / "bin"
    real_run = subprocess.run
    # Isolate the login PATH probe. The real login-shell/PowerShell path is tested separately.
    def run(argv, **kwargs):
        if argv == ["bash", "-lc", "command -v duoterm"]:
            return subprocess.CompletedProcess(argv, 0, str(binaries / "duoterm") + "\n", "")
        return real_run(argv, **kwargs)
    monkeypatch.setattr(setup.subprocess, "run", run)
    state = tmp_path / "state"
    result = setup.initialize(source, state, tmp_path / "install", binaries)
    assert result["complete"], result
    assert setup.initialize(source, state, tmp_path / "install", binaries)["skipped"]
    assert not setup.initialize(source, state, tmp_path / "install", binaries, recheck=True)["skipped"]
    # Move downloaded sources away: installed CLI must be independent of them.
    source.rename(tmp_path / "removed-download")
    result = real_run([str(binaries / "duoterm"), "doctor", "--smoke", "--json"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"]
