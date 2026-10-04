# Reproduction bundle (deliverable 4)

Regenerates every number this repo reports for the **LiDAR tier** from the **raw inputs**
using one script. Deterministic: fixed seeds, positional tie-breaks, no RNG — running it
twice yields byte-identical `plan.json` (modulo timing fields).

## Prerequisites

- A clean machine with the repo and Python 3.11+; set up once with
  `scripts/bootstrap.sh` (creates `.venv`, editable install, runs the tests).
- The **raw seed capture binaries** (`depth/`, `confidence/`, `rgb.mp4`) — these are large
  and **git-ignored**, so restore them from the submitted volume/archive into:

  ```
  single_room/c00a170fe1/
  single_scan_floor_only/1a8384c3f6/
  single_scan_with_ceiling/c7d28f72c6/
  ```

  (The repo already contains their metadata: `odometry.csv`, `camera_matrix.csv`, `imu.csv`.)

## Run

```bash
scripts/reproduce.sh                      # all three seeds -> out/
scripts/reproduce.sh single_room/c00a170fe1 --out /tmp/repro   # one capture
```

It performs four steps and prints a summary table:

1. **B-0 depth-unit verification** (ADR-0002) → `out/b0_depth_units.json`
   (camera height ≈ 1.40–1.46 m across the seeds; only millimetres is plausible).
2. **`scan2plan run`** on each seed (S1 ingest → S7 damage) →
   `out/<id>/{plan.json,plan.svg,ablation.svg,stage1_observed.*,stage2_walls.*,stage3_rooms.json,damage.json}`.
3. **`scan2plan validate`** on every `plan.json` (I3 schema + referential integrity).
4. A printed table of rooms / openings / coverage / invariant failures / connectors /
   overlap / damage / scope per capture.

## What this does NOT regenerate (and why)

These require **manual work** that is not in the repo, and are disclosed in
`docs/compliance-matrix.md`:

- **Benchmark gates** (G-OPEN, G-CEIL, G-REP, G-CAL, G-PSTITCH, G-TIERACC) — need **laser
  ground truth (BM-5)**, which must be measured in the room.
- **Head-to-head table** (Part 3) — needs a consumer-app capture + its export.
- **Fix-loop before/after bundle** — the fixes and their evidence exist
  (`CHANGELOG.md`, `bench/stage2_before|after/`, `out/before_ceiling_fix/`), but packaging the
  regenerable `messages/fix_loop/{before,after}` bundle is pending.
- **Photos / video tiers** — recon front-ends not implemented (plan `04b` B-2/B-3).

## Artifact map

| Artifact | Produced by | Content |
|---|---|---|
| `out/b0_depth_units.json` | `scripts/verify_depth_units.py` | depth-scale evidence |
| `out/<id>/plan.json` | `scan2plan run` (S9) | CIR → published schema (I3) |
| `out/<id>/plan.svg` | `scan2plan run` | dimensioned plan + damage overlay |
| `out/<id>/ablation.svg` | `scan2plan run` | loop-closure on/off footprints (G-DRIFT) |
| `out/<id>/stage1_observed.*` | S1 | observed-evidence layer |
| `out/<id>/stage2_walls.*` | S2 | wall reconstruction + graph |
| `out/<id>/stage3_rooms.json` | S3 | rooms + invariants |
| `out/<id>/damage.json` | S5–S7 | damage / concealed / scope + thresholds |
