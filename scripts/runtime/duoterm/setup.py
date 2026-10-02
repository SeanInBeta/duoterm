"""One-time, resumable installation and explicit diagnostics. No third-party dependencies."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import uuid
import venv

from . import __version__


def source_hash(source: Path) -> str:
    entries = [f"{p.relative_to(source).as_posix()}:{hashlib.sha256(p.read_bytes()).hexdigest()}"
               for p in sorted(source.rglob("*.py")) if "__pycache__" not in p.parts]
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()


def load_record(home: Path) -> dict:
    try:
        data = json.loads((home / "setup.json").read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_record(home: Path, record: dict) -> None:
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    # JSON is authoritative. Never enable setup based on a manually checked Markdown box.
    _atomic(home / "setup.json", json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    mark = "x" if record.get("complete") else " "
    lines = ["# duoterm 初始化状态", "", f"- [{mark}] 首次环境检查已完成", "",
             f"阶段：{record.get('stage', 'pending')}", f"运行版本：{record.get('runtime_version', __version__)}", ""]
    for item in record.get("checks", []):
        lines.append(f"- [{'x' if item['ok'] else ' '}] {item['name']}: {item['detail']}")
    if record.get("error"):
        lines.extend(["", f"待处理：{record['error']}"])
    _atomic(home / "setup.md", "\n".join(lines) + "\n")


def doctor(smoke: bool = False) -> dict:
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    add("python", sys.version_info >= (3, 10), sys.version.split()[0])
    add("platform", sys.platform.startswith("linux"), sys.platform + " (Linux/WSL required)")
    for name in ("tmux", "ssh", "bash", "infocmp"):
        add(name, shutil.which(name), shutil.which(name) or "missing")
    add("venv", True, "Python venv module available")
    if shutil.which("infocmp"):
        p = subprocess.run(["infocmp", "screen-256color"], capture_output=True, text=True)
        add("screen-256color", p.returncode == 0, "terminfo present" if not p.returncode else p.stderr.strip())
    if smoke and all(item["ok"] for item in checks):
        from .core import Terminal
        from . import tmux as tm
        names = ("DUOTERM_TMUX_SOCKET", "DUOTERM_TMUX_CONFIG", "DUOTERM_AUTO_INTEGRATE", "DUOTERM_TERM", "DUOTERM_PROMPT_RE", "DUOTERM_SESSION")
        previous = {name: os.environ.get(name) for name in names}
        socket = "duoterm-doctor-" + uuid.uuid4().hex[:12]
        try:
            for name in names:
                os.environ.pop(name, None)
            os.environ.update(DUOTERM_TMUX_SOCKET=socket, DUOTERM_TMUX_CONFIG="/dev/null", DUOTERM_AUTO_INTEGRATE="1")
            with tempfile.TemporaryDirectory(prefix="duoterm-doctor-") as tmp:
                for label, legacy in (("bash", False), ("bash-legacy-mode", True)):
                    t = Terminal(label, home=Path(tmp))
                    command = "env HISTFILE=/dev/null PS1='$ ' " + ("DUOTERM_SI_LEGACY=1 " if legacy else "")
                    command += shlex.quote(shutil.which("bash")) + " --noprofile --norc"
                    t.start(command=command)
                    t._wait_for_prompt(5)
                    result = t.run("printf 'duoterm-ready'", timeout=10)
                    ok = result.output == "duoterm-ready" and result.exit_code == 0
                    add(label + "-output", ok, result.output)
                    add(label + "-exit", t.run("false", timeout=10).exit_code == 1, "nonzero exit code")
                    add(label + "-integration", t.status()["shell_integration"], "OSC 133 in raw log")
                    add(label + "-log", "duoterm-ready" in t.read_new(), "incremental read")
                    add(label + "-term", t.run("printf '%s' \"$TERM\"").output == "screen-256color", "shared pane TERM")
        except Exception as exc:
            add("smoke", False, str(exc))
        finally:
            try:
                tm.tmux("kill-server", check=False)  # Only the UUID-named test server.
            finally:
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
    return {"ok": all(item["ok"] for item in checks), "runtime_version": __version__, "checks": checks}


def initialize(source: Path, setup_home: Path, install_home: Path, bin_home: Path,
               recheck: bool = False, repair_path: bool = False) -> dict:
    fingerprint = source_hash(source)
    record = load_record(setup_home)
    if (not recheck and record.get("complete") and record.get("source_hash") == fingerprint
            and Path(record.get("runtime_path", ""), "entry.py").is_file()
            and Path(record.get("python", "")).is_file() and (bin_home / "duoterm").is_file()):
        return {**record, "skipped": True}
    record = {"schema_version": 1, "complete": False, "runtime_version": __version__,
              "source_hash": fingerprint, "stage": "installing", "checks": [],
              "backend": {"platform": "linux", "user": os.environ.get("USER", "")}}
    save_record(setup_home, record)
    try:
        runtime = install_home / "runtime" / fingerprint[:16]
        runtime.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, runtime / "duoterm", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        environment = install_home / "venv"
        python = environment / "bin" / "python"
        if not python.exists():
            venv.EnvBuilder(with_pip=False).create(environment)
        (runtime / "entry.py").write_text("from duoterm.cli import main\nraise SystemExit(main())\n", encoding="utf-8")
        (runtime / "bridge.py").write_text(
            "import base64, json, sys\nfrom duoterm.cli import main\n"
            "payload = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))\n"
            "import os\n"
            "args = payload.get('args') if isinstance(payload, dict) else payload\n"
            "allowed = {'DUOTERM_TMUX_SOCKET', 'DUOTERM_TMUX_CONFIG', 'DUOTERM_HOME', 'DUOTERM_TERM', 'DUOTERM_AUTO_INTEGRATE', 'DUOTERM_PROMPT_RE'}\n"
            "for key, value in (payload.get('env', {}) if isinstance(payload, dict) else {}).items():\n"
            "    if key not in allowed or not isinstance(value, str) or '\\x00' in value: raise SystemExit('Invalid duoterm environment')\n"
            "    os.environ[key] = value\n"
            "if not isinstance(args, list) or not all(isinstance(a, str) and '\\x00' not in a for a in args):\n"
            "    raise SystemExit('Invalid duoterm argument payload')\nraise SystemExit(main(args))\n", encoding="utf-8")
        bin_home.mkdir(parents=True, exist_ok=True)
        launcher = bin_home / "duoterm"
        launcher.write_text(f"#!/bin/sh\nexec {shlex.quote(str(python))} {shlex.quote(str(runtime / 'entry.py'))} \"$@\"\n", encoding="utf-8")
        launcher.chmod(0o755)
        record.update(runtime_path=str(runtime), python=str(python), cli=str(launcher), stage="checking")
        save_record(setup_home, record)
        p = subprocess.run([str(python), str(runtime / "entry.py"), "doctor", "--smoke", "--json"],
                           capture_output=True, text=True, timeout=90)
        report = json.loads(p.stdout)
        record["checks"] = report["checks"]
        if p.returncode or not report["ok"]:
            raise RuntimeError("runtime checks failed; see setup.md")
        # Verify the command actually resolves in a newly opened login shell.
        p = subprocess.run(["bash", "-lc", "command -v duoterm"], capture_output=True, text=True)
        on_path = p.returncode == 0 and p.stdout.strip() == str(launcher)
        if not on_path and repair_path:
            profile = Path.home() / ".profile"
            original = profile.read_text() if profile.exists() else ""
            line = f"export PATH={shlex.quote(str(bin_home))}:\"$PATH\""
            if line not in original.splitlines():
                _atomic(profile, original + "\n# duoterm CLI\n" + line + "\n")
            p = subprocess.run(["bash", "-lc", "command -v duoterm"], capture_output=True, text=True)
            on_path = p.returncode == 0 and p.stdout.strip() == str(launcher)
        record["checks"].append({"name": "login-shell-path", "ok": on_path, "detail": str(launcher)})
        if not on_path:
            raise RuntimeError("CLI installed, but login-shell PATH needs repair. Review ~/.profile, then rerun with --repair-path.")
        record.update(complete=True, stage="ready")
    except Exception as exc:
        record.update(complete=False, stage="blocked", error=str(exc))
    save_record(setup_home, record)
    return {**record, "skipped": False}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=Path(__file__).parent)
    p.add_argument("--recheck", action="store_true")
    p.add_argument("--repair-path", action="store_true")
    args = p.parse_args()
    result = initialize(args.source.resolve(), Path(os.environ.get("DUOTERM_SETUP_HOME", Path.home() / ".duoterm")),
                        Path(os.environ.get("DUOTERM_INSTALL_HOME", Path.home() / ".local/share/duoterm")),
                        Path(os.environ.get("DUOTERM_BIN_HOME", Path.home() / ".local/bin")),
                        args.recheck, args.repair_path)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("complete") else 125


if __name__ == "__main__":
    raise SystemExit(main())
