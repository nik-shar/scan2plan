#!/usr/bin/env bash
# One command per capture (plan 02 section 2 / plan 04g OUT-7).
#
#   scripts/run_capture.sh <capture_dir> [out_dir] [-- run flags]
#
# <capture_dir> is either an already-conformant I1 bundle (odometry.csv + depth/) or a
# raw LiDAR-logger export, which is first normalised by scripts/build_bundle.sh.
# Writes out/<capture_id>/{plan.json,plan.svg,stage1_observed.*,stage2_walls.*,stage3_rooms.json}.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
fi

CAPTURE="${1:?usage: run_capture.sh <capture_dir> [out_dir] [-- run flags]}"
shift || true

OUT="out"
if [ $# -gt 0 ] && [ "${1:0:1}" != "-" ]; then
  OUT="$1"
  shift
fi

# A raw export (no odometry.csv, or depth in depth_m/) is normalised first.
if [ ! -f "$CAPTURE/odometry.csv" ] || { [ ! -d "$CAPTURE/depth" ] && [ -d "$CAPTURE/depth_m" ]; }; then
  echo "==> raw export detected: building an I1 bundle into bundles/"
  BUILT=$("$PYTHON" -m scan2plan.ingest.build "$CAPTURE" --out bundles | tail -n 1 | awk '{print $2}')
  echo "==> bundle: $BUILT"
  CAPTURE="$BUILT"
fi

echo "==> scan2plan run $CAPTURE --out $OUT"
exec "$PYTHON" -m scan2plan.cli run "$CAPTURE" --out "$OUT" "$@"
