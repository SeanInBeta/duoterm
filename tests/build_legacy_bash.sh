#!/usr/bin/env bash
# Build the official downloaded Bash 4.2 source locally; never install system-wide.
set -euo pipefail
cd "$(dirname "$0")/.."
test -f .verification/bash-4.2.tar.gz
mkdir -p .verification/legacy-build
tar -xzf .verification/bash-4.2.tar.gz -C .verification/legacy-build
cd .verification/legacy-build/bash-4.2
./configure --without-bash-malloc > configure.log 2>&1
make -j2 > build.log 2>&1
./bash --version | head -1
