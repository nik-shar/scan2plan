#!/usr/bin/env bash
# Build a conformant interface-I1 capture bundle from a raw LiDAR-logger export.
# Plan 03 (Part 1 capture), task P1-3. See docs/protocol.md for the capture route.
#
#   scripts/build_bundle.sh <raw_export_dir> --out bundles --device "iPhone 15 Pro" \
#       --app "<logger>" --app-version "<ver>" --rooms-expected 1
#
# The bundle is validated by re-loading it (scan2plan.ingest.bundle.load_bundle), so a
# successful build is guaranteed to ingest.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
fi

exec "$PYTHON" -m scan2plan.ingest.build "$@"
