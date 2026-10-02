#!/usr/bin/env bash
# M0 bootstrap: create a venv, install scan2plan, run the tests.
# See docs/plans/02-foundation-repo-and-infra.md section 2 (clean-machine < 15 min).
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"

echo "==> creating venv (.venv)"
"$PYTHON" -m venv .venv

# shellcheck disable=SC1091
. .venv/bin/activate

python -m pip install --upgrade pip
echo "==> installing scan2plan (editable) with dev + cli extras"
pip install -e ".[dev,cli]"

echo "==> running tests"
pytest -q

echo "==> done. next:  scan2plan --help"