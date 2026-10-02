#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .verification/venv/bin/python ]]; then python3 -m venv .verification/venv; fi
if .verification/venv/bin/python -c 'import pytest' >/dev/null 2>&1; then
    :
elif [[ -d .verification/wheels ]]; then
    .verification/venv/bin/pip install -q --no-index --find-links=.verification/wheels 'pytest>=7'
else
    .verification/venv/bin/pip install -q --timeout 15 --retries 1 'pytest>=7'
fi
.verification/venv/bin/python -m pytest "$@"
