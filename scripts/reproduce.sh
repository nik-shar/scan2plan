#!/usr/bin/env bash
# Reproduction bundle (deliverable 4, plan 09 section 3).
#
# Regenerate every number this repo reports for the LiDAR tier from the RAW inputs:
#   1. B-0 depth-unit verification (ADR-0002)          -> out/b0_depth_units.json
#   2. scan2plan run on each seed capture              -> out/<id>/{plan.json,plan.svg,
#        ablation.svg,stage1_observed.*,stage2_walls.*,stage3_rooms.json,damage.json}
#   3. schema-validate every plan.json (I3)
#   4. print a summary of the reported numbers
#
# Usage:
#   scripts/reproduce.sh [capture_dir ...] [--out DIR]
#
# Deterministic: fixed seeds, positional tie-breaks, no RNG. Running twice yields
# byte-identical plan.json (modulo timing fields).
#
# NOT regenerated here (needs manual work, disclosed): the benchmark gates, the
# head-to-head table and the fix-loop before/after require LASER GROUND TRUTH (BM-5)
# and a consumer-app capture. See docs/compliance-matrix.md.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
fi

OUT="out"
CAPTURES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    *) CAPTURES+=("$1"); shift ;;
  esac
done
if [ ${#CAPTURES[@]} -eq 0 ]; then
  CAPTURES=(
    "single_room/c00a170fe1"
    "single_scan_floor_only/1a8384c3f6"
    "single_scan_with_ceiling/c7d28f72c6"
  )
fi

echo "==> [1/4] B-0 depth-unit verification (ADR-0002)"
"$PYTHON" scripts/verify_depth_units.py --json "$OUT/b0_depth_units.json"

echo "==> [2/4] scan2plan run (LiDAR tier, S1-S7) + [3/4] schema validate"
RUNS=()
for cap in "${CAPTURES[@]}"; do
  if [ ! -d "$cap/depth" ]; then
    echo "    SKIP $cap (no depth/ - the seed binaries are git-ignored; see repro/README.md)"
    continue
  fi
  echo "    run  $cap"
  "$PYTHON" -m scan2plan.cli run "$cap" --out "$OUT" > "$OUT/$(basename "$cap").reproduce.log" 2>&1
  "$PYTHON" -m scan2plan.cli validate "$OUT/$(basename "$cap")/plan.json"
  RUNS+=("$cap")
done

echo "==> [4/4] reported numbers"
"$PYTHON" - "$OUT" "${RUNS[@]}" <<'PY'
import json, sys
from pathlib import Path

out = Path(sys.argv[1])
rows = []
for cap in sys.argv[2:]:
    cid = Path(cap).name
    d = out / cid
    if not (d / "plan.json").is_file():
        continue
    plan = json.loads((d / "plan.json").read_text())
    s3 = json.loads((d / "stage3_rooms.json").read_text())
    dmg = json.loads((d / "damage.json").read_text())
    stitch = plan.get("stitch") or {}
    cov = next((i["values"].get("share") for i in s3.get("invariants", [])
                if i["name"] == "coverage"), None)
    rows.append({
        "capture": cid, "rooms": s3.get("room_count"),
        "openings": len(plan.get("openings") or []),
        "coverage": cov,
        "inv_failed": s3.get("invariants_failed"),
        "connectors": len(stitch.get("edges") or []),
        "overlap_ok": stitch.get("overlap_ok"),
        "damages": dmg.get("damage_count"), "scope": dmg.get("scope_count"),
    })

cols = ["capture", "rooms", "openings", "coverage", "inv_failed",
        "connectors", "overlap_ok", "damages", "scope"]
print("  " + " | ".join(cols))
for r in rows:
    print("  " + " | ".join(str(r[c]) for c in cols))
print(f"\n  regenerated {len(rows)} capture(s) into {out}/")
PY

echo "==> done."
