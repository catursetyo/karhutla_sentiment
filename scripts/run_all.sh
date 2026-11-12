#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 scripts/collect.py "$@"
python3 scripts/clean.py
python3 scripts/label.py
python3 scripts/split.py
