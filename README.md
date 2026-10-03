# scan2plan

Phone capture → **stitched, dimensioned whole-property floor plan + damage
assessment**, from three input tiers (photos, video, LiDAR), with a confidence
interval on every measurement.

Applied AI Engineer case study submission (Aug 2026).

> **Status: stage 1 frozen (`stage1-frozen`); stage 2 walls + stage 3 rooms landed.**
> Repo scaffold, config (I4), utilities, CLI (I5), frozen CIR (I2), published schema
> (I3), and the confirmed B-0 depth-unit check are in place. Stage 1 is the
> **observed-evidence** layer, stage 2 is **multi-segment wall extraction**
> (completion + node/edge graph), and stage 3 (`scan2plan.geometry.rooms.build_stage3`)
> turns them into **closed, dimensioned rooms** — greedy cost-ordered closure,
> flood-filled regions with doorway-shaped waist splits, per-room polygons (L-shapes
> supported), Monte-Carlo intervals on every number, ceiling (with a prior when not
> seen) and openings/adjacency. `scan2plan run` (LiDAR tier) writes
> `stage1_observed.*`, `stage2_walls.*`, `stage3_rooms.json`, a populated schema-valid
> `plan.json` (`status="computed"`) and `plan.svg`. **No vision model is used in
> stages 1–3.** `scan2plan ablate` / stitch / damage / calibration (S4–S8) land later;
> `scan2plan ablate` emits the stage-1/2/3 artifacts + plan and honestly reports that
> the drift ablation is not computed. See `docs/plans/` and `docs/plans/04i-stage3.md`.

## Interfaces (frozen contracts)

The design is organised around nine single-owner interfaces; `docs/plans/README.md`
§3 is the authoritative matrix.

| ID | Interface | Owner doc |
|---|---|---|
| I1 | Raw capture bundle | `03` |
| I2 | CIR (Canonical Intermediate Representation) | `04a` |
| I3 | Published output JSON schema (`plan.json`) | `04a` |
| I4 | Config schema (`config.schema.json`) | `02` |
| I5 | CLI contract (`scan2plan <cmd>`) | `04g` |
| I6 | Measurement + uncertainty type | `04f` |
| I7 | Coordinate frames + units | `01` |
| I8 | Recon artifact (per tier) | `04b` |
| I9 | Benchmark manifest + ground truth | `08` |

## Quickstart (clean machine)

```bash
scripts/bootstrap.sh          # venv + editable install + tests
source .venv/bin/activate
scan2plan --help
```

Requires Python 3.11+.

## CLI

```
scan2plan run <capture_dir> [--config cfg.yaml] [--out out/]   # S1+S2 + stage-1 evidence + stage-2 walls + stub plan
scan2plan ingest <capture_dir>                                 # S1 only
scan2plan ablate --capture <id> --feature loop_closure         # pending stage 2/3 redesign
scan2plan bench [--tier photos|video|lidar]                    # benchmark gates
scan2plan report                                               # report tables
scan2plan validate <plan.json>                                 # I3 schema check
```

## Layout

```
src/scan2plan/          # package (cli.py, config.py, util/, cir/, ingest/, recon/, geometry/, render/)
archive/old_stage23/    # pre-redesign stage 2/3 (outline/classification/snapping), kept for reference
docs/plans/             # implementation plans (master + per-part/module)
docs/stage1_contract.md # stage-1 observed-evidence contract (grid, thresholds, files)
docs/schema/            # JSON schemas (I3/I4/I9)
bench/                  # benchmark data + ground truth + runner
scripts/                # bootstrap / fetch_weights / build_bundle
tests/                  # pytest suite
single_room/ single_scan_*/   # seed captures (I1, LiDAR tier; large assets git-ignored)
```

## Seed captures

Three LiDAR-tier captures ship with the repo (metadata only; `rgb.mp4`, `depth/`
and `confidence/` are git-ignored as large binaries — see `docs/plans/02` §6):

| Path | Rooms | Frames | Duration |
|---|---|---|---|
| `single_room/c00a170fe1/` | 1 | 1715 | ~29 s |
| `single_scan_floor_only/1a8384c3f6/` | **multiple** | 5251 | ~88 s |
| `single_scan_with_ceiling/c7d28f72c6/` | 1 | 9745 | ~162 s |

Note: `single_scan_floor_only/1a8384c3f6` is a **multi-room** capture — the camera
travels ~54 m (vs ~14 m for `single_room`), covering more than one room, so it is
not a single-room scan. Stages beyond stage 1 (which would segment and stitch
rooms) are being redesigned and are not computed yet.

## Development

```bash
pip install -e ".[dev,cli]"
ruff check . && ruff format --check .
python -m mypy --strict src/scan2plan/cir
pytest -q
```

Verify the seed depth units (task B-0, confirms `depth_scale_m = 0.001` / mm):

```bash
python scripts/verify_depth_units.py --json out/b0_depth_units.json
```