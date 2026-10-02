# scan2plan

Phone capture → **stitched, dimensioned whole-property floor plan + damage
assessment**, from three input tiers (photos, video, LiDAR), with a confidence
interval on every measurement.

Applied AI Engineer case study submission (Aug 2026).

> **Status: M0 (foundation).** Repo scaffold, interfaces, config (I4), utilities
> and the CLI skeleton (I5) exist. The pipeline stages (S1–S9) are not implemented
> yet — they land at milestones M1–M9. See `docs/plans/`.

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
scan2plan run <capture_dir> [--config cfg.yaml] [--out out/]   # S1..S9 (one command)
scan2plan ingest <capture_dir>                                 # S1 only
scan2plan ablate --capture <id> --feature loop_closure         # drift on/off (G-DRIFT)
scan2plan bench [--tier photos|video|lidar]                    # benchmark gates
scan2plan report                                               # report tables
scan2plan validate <plan.json>                                 # I3 schema check
```

## Layout

```
src/scan2plan/          # package (cli.py, config.py, util/, cir/, ingest/, recon/, ...)
docs/plans/             # implementation plans (master + per-part/module)
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
| `single_scan_floor_only/1a8384c3f6/` | 1 | 5251 | ~88 s |
| `single_scan_with_ceiling/c7d28f72c6/` | 1 | 9745 | ~162 s |

## Development

```bash
pip install -e ".[dev,cli]"
ruff check . && ruff format --check .
pytest -q
```