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
  (5 cm) of a fitted segment; also reported over the support-gated `kept` cells and
  split into `wall_like_explained` / `dense_blobs` / `residual_noise`. In
  `stage2_walls.svg` wall-like cells are grey, dense blobs orange, residual noise
  pale red.

## 2. Summary (three seeds, default stride)

| capture | angle | before (rect) | segments (obs/inf) | open_space | bridges (occl/dropout) + ext | after (all) | after (kept) | median wall-CI |
|---|---|---|---|---|---|---|---|---|
| `c00a170fe1` | 22.5° | 11.5% | **11** (9/2) | 0 | 1 / 0 + 1 | 21.0% | 58.9% | ±1.8 cm |
| `1a8384c3f6` | 87.0° | 5.1% | **35** (21/14) | 1 | 4 / 0 + 12 | 14.9% | 36.1% | ±3.2 cm |
| `c7d28f72c6` | 28.5° | 3.8% | **39** (27/12) | 1 | 4 / 0 + 10 | 16.6% | 40.4% | ±3.2 cm |

The rectangle explained only 4–11% of the wall cells and could not represent the
target capture's **inner walls, wing and enclosed block**. Multi-segment extraction
plus completion finds many more walls (11 / 35 / 39, each with observed and inferred
pieces) and roughly doubles the explained share; over the plausible (support-gated)
cells it reaches 36–59%. After the completion→merge cleanup (this revision) the two
large captures carry one **`open_space`** each (a >2.5 m camera-crossed walk-through,
previously mislabelled an opening).

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

A gap between collinear segments that the **camera path crossed** is classified by
width: in [`open_min_m`, `open_max_m`] (0.5–2.5 m) it is an **`opening`**; narrower
→ `inferred_dropout`; wider → **`open_space`** (a walk-through, not a door).
`bridges` are inferred wall pieces that close a broken line: furniture in front
(`inferred_occluded`) or a short sensor dropout (`inferred_dropout`). `extensions`
reach a dangling end to a perpendicular wall. Every inferred piece's interval
half-width is `ci_base_m + ci_per_m · L`.

| capture | openings | open_space | occluded | dropout | extensions | unknown gaps |
|---|---|---|---|---|---|---|
| `c00a170fe1` | 0 | 0 | 1 | 0 | 1 | 0 |
| `1a8384c3f6` | 0 | 1 | 4 | 0 | 12 | 0 |
| `c7d28f72c6` | 0 | 1 | 4 | 0 | 10 | 0 |

The two real-capture camera-crossed gaps are wide (5.23 m and 6.57 m), so the width
cap records them as **`open_space`** rather than a door — the literal fix for the
"wide gap mislabelled an opening" limitation. No evidence-free gap long enough to
stay `unknown` survived on the seeds.

## 3c. Wall graph (`geometry/wall_graph.py`)

After completion the pieces are **merged** (`merge_wall_pieces`: parallel same-axis,
offset within `merge_tol_m`, overlapping spans → one wall with `thickness_m`), then
wall intersections become **nodes** and merged wall runs become **edges**. **All**
nodes within `node_merge_m` (line ends included) are merged *before* the nodes are
re-typed. Node types: `L` (corner), `T`, `cross`, `dangling_end` (a free end, also
flagged). Every dangling node also appears in `dangling_ends[]` with a uv + world
location, so open ends are never silent.

| capture | nodes | edges | L | T | cross | dangling_end |
|---|---|---|---|---|---|---|
| `c00a170fe1` | 15 | 11 | 3 | 2 | 0 | 10 |
| `1a8384c3f6` | 42 | 42 | 8 | 11 | 4 | 19 |
| `c7d28f72c6` | 52 | 62 | 6 | 24 | 6 | 16 |

`c00a170fe1` (`single_room`) is still fragmentary — 10 of 15 nodes are dangling ends
— because it is a short, furniture-heavy partial scan; the two longer walks
(`1a8384c3f6`, `c7d28f72c6`) yield richer graphs with cross junctions. Node drawing:
L = circle, T = square, cross = diamond, dangling = red ring.

## 3d. Cleanup: wall merge, opening cap, evidence split, length report

- **Opening-width cap** (I4 `open_min_m` 0.5 / `open_max_m` 2.5) — see §3b.
- **Wall merge** (`merge_wall_pieces`): collapses parallel same-axis pieces (offset
  within `merge_tol_m` 0.25, overlapping or same-provenance abutting spans) into one
  wall with `thickness_m`; a completion bridge that merely abuts keeps its own
  provenance. Effect: `1a8384c3f6` **37→35** walls, `c7d28f72c6` **41→39** walls
  (11 thick each; 1 on `c00a170fe1`). Node counts are unchanged.
- **Length report** (`lengths`): observed vs inferred wall length and the longest
  inferred run.

  | capture | observed m | inferred m | longest inferred run m | runs > `max_extend_m` |
  |---|---|---|---|---|
  | `c00a170fe1` | 16.98 | 6.48 | 5.98 | 1 |
  | `1a8384c3f6` | 49.04 | 25.18 | 4.51 | 11 |
  | `c7d28f72c6` | 64.46 | 24.65 | 4.67 | 6 |

- **Evidence split** (`evidence`): every wall cell is `wall_like_explained` /
  `dense_blobs` (a `blob_bin_m` 0.10 bin with ≥ `blob_min_cells` 6 unexplained cells
  — furniture/occluder) / `residual_noise`. Shares of all wall cells:

  | capture | wall_like | dense_blobs | residual_noise |
  |---|---|---|---|
  | `c00a170fe1` | 21.0% | 74.3% | 4.7% |
  | `1a8384c3f6` | 14.9% | 70.4% | 14.7% |
  | `c7d28f72c6` | 16.6% | 72.8% | 10.6% |

  Most of the unexplained mass is therefore **dense blobs** (furniture/occluder),
  not scattered speckle.
- **Node / cross report** (`merge`): reported before→after. **Crosses do not drop**
  (0→0, 4→4, 6→6). Reason: the crossings are genuine 4-way meetings of interior
  walls; the near-parallel wall pairs that inflate the count (e.g. `v=5.238` vs
  `v=5.552`, Δ 0.31 m) sit just above `merge_tol_m` 0.25, so the merge correctly
  leaves them as two walls. Reported as a warning, never silenced.

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
