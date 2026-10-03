# 04i — Stage 2 report: multi-segment walls vs the rectangle (before/after)

**Status:** implemented. **before** = the rejected minimum-bounding-rectangle stage 2
(git tag `stage2-rectangle`); **after** = multi-segment extraction from the frozen
stage-1 artifact only. Both were generated on the **same** stage-1 artifacts
(`scan2plan run <capture>` at the default stride); snapshots are committed under
`bench/stage2_before/` and `bench/stage2_after/`.

## 1. Method

- **before** (rectangle): the four outermost Manhattan lines, each clipped to the
  room extent — a closed rectangle.
- **after** (segments): support gate (`min_height_bins`) → Manhattan angle →
  **every** histogram peak per axis → contiguous runs ≥ `min_run_m` (gap ≤
  `run_gap_m`) → merge parallel segments within `merge_tol_m` (thickness) → join
  L/T junctions within `join_tol_m` (extensions marked `inferred`, interval widened
  by the extension length).
- **evidence_explained** = share of stage-1 wall **cells** within `evidence_tol_m`
  (5 cm) of a fitted segment; also reported over the support-gated `kept` cells.
  Unexplained cells are drawn **red** in `stage2_walls.svg`.

## 2. Summary (three seeds, default stride)

| capture | angle | before (rect) | segments (obs/inf) | openings | bridges (occl/dropout) + ext | after (all) | after (kept) | unexplained | median wall-CI |
|---|---|---|---|---|---|---|---|---|---|
| `c00a170fe1` | 22.5° | 11.5% | **11** (9/2) | 0 | 1 / 0 + 1 | 21.0% | 58.9% | 17,383 | ±1.8 cm |
| `1a8384c3f6` | 87.0° | 5.1% | **37** (21/16) | 1 | 4 / 0 + 12 | 14.9% | 36.1% | 32,551 | ±3.2 cm |
| `c7d28f72c6` | 28.5° | 3.8% | **41** (27/14) | 1 | 4 / 0 + 10 | 16.6% | 40.4% | 42,400 | ±3.2 cm |

The rectangle explained only 4–11% of the wall cells and could not represent the
target capture's **inner walls, wing and enclosed block**. Multi-segment extraction
plus completion finds many more walls (11 / 37 / 41, each with observed and inferred
pieces) and roughly doubles the explained share; over the plausible (support-gated)
cells it reaches 36–59%.

## 3. `c00a170fe1` (the target capture) — segments after

| id | axis | offset_m | length_m ± | start | end | cov | sup | thick | prov |
|---|---|---|---|---|---|---|---|---|---|
| wall_1 | u | -5.531 | 1.55 ± 0.015 | 2.46 | 4.01 | 1.00 | 237 | 0.000 | observed |
| wall_2 | u | -4.126 | 1.20 ± 0.012 | 1.37 | 2.57 | 0.96 | 162 | 0.000 | observed |
| wall_3 | u | -0.062 | 1.15 ± 0.011 | 1.90 | 3.05 | 0.96 | 174 | 0.000 | observed |
| wall_4 | u | 2.358 | 5.98 ± 0.104 | -1.10 | 4.87 | 0.98 | 934 | 0.000 | inferred |
| wall_5 | v | -1.103 | 1.20 ± 0.012 | -1.14 | 0.06 | 0.96 | 151 | 0.000 | observed |
| wall_6 | v | -1.103 | 1.79 ± 0.018 | 0.56 | 2.36 | 0.95 | 188 | 0.000 | observed |
| wall_7 | v | 1.901 | 2.42 ± 0.024 | -0.06 | 2.36 | 1.00 | 345 | 0.000 | observed |
| wall_8 | v | 3.217 | 1.27 ± 0.013 | 1.09 | 2.36 | 1.00 | 139 | 0.000 | observed |
| wall_9 | v | 3.608 | 3.80 ± 0.038 | -3.63 | 0.17 | 1.00 | 483 | 0.000 | observed |
| wall_10 | v | 4.873 | 2.60 ± 0.026 | -0.24 | 2.36 | 0.96 | 696 | 0.197 | observed |

Interior lines are now present (e.g. `u=-0.062`, `u=-4.126`, `v=1.901`, `v=3.217`)
alongside the envelope lines; `wall_10` is a **merged** double-face wall
(`merged_from=2`, thickness 0.197 m); `wall_6`/`wall_7` split at a doorway gap
(0.06 → 0.56 m). `wall_4` is `inferred` (extended to meet a junction) and its
interval (±0.104 m) reflects that extension.

## 3b. Completion outcomes (`geometry/wall_complete.py`)

`openings` are gaps between collinear segments that the **camera path crossed**
(never bridged). `bridges` are inferred wall pieces that close a broken line:
furniture in front (`inferred_occluded`) or a short sensor dropout
(`inferred_dropout`). `extensions` reach a dangling end to a perpendicular wall.
Every inferred piece's interval half-width is `ci_base_m + ci_per_m · L`.

| capture | openings | occluded | dropout | extensions | unknown gaps |
|---|---|---|---|---|---|
| `c00a170fe1` | 0 | 1 | 0 | 1 | 0 |
| `1a8384c3f6` | 1 | 4 | 0 | 12 | 0 |
| `c7d28f72c6` | 1 | 4 | 0 | 10 | 0 |

The two real-capture openings are wide (5.23 m and 6.57 m): the camera crossed a
large collinear gap, which the literal rule records as a single opening (a wide
passage, or two wall runs with a walk-through between them). No evidence-free gap
long enough to stay `unknown` survived on the seeds.

## 4. Honest limitations

- **`evidence_explained` over *all* cells is low (15–21%)** because ~58% of stage-1
  wall cells are single-height-bin noise (ghosts/furniture/door frames) that the
  support gate already drops; the metric over the `kept` cells (36–59%) is the more
  meaningful one. Both are reported.
- **Stage-1 layer cap.** `EVIDENCE_LAYER_CAP = 60,000` truncates the two large
  captures' wall-cell lists, so stage 2 fits a deterministic subsample and warns
  `stage1_layer_capped` (fix-loop material, plan `06`).
- **Interior/occluded walls are partly recovered**; `min_run_m = 1.2 m` still drops
  short partitions, and mirror/glass faces are not specially handled (the class
  from the old stage 2 is not replicated here).
