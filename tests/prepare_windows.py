"""Build an isolated installed runtime for native Windows-to-WSL bridge tests."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/runtime"))
from duoterm import setup

work = Path(sys.argv[1]).resolve()
source = Path(setup.__file__).parent
binaries = work / "bin"
real_run = subprocess.run


def run(argv, **kwargs):
    # Only PATH is synthetic; runtime installation, smoke tests and all forwarding are real.
    if argv == ["bash", "-lc", "command -v duoterm"]:
        return subprocess.CompletedProcess(argv, 0, str(binaries / "duoterm") + "\n", "")
    return real_run(argv, **kwargs)


setup.subprocess.run = run
record = setup.initialize(source, work / "linux-state", work / "install", binaries)
if not record.get("complete"):
    raise SystemExit(json.dumps(record))
record["backend"] = {"platform": "wsl", "distro": sys.argv[2], "user": sys.argv[3]}
setup.save_record(work / "windows-state", record)
print(json.dumps(record))
