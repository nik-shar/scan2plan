# Changelog

Honest milestone log (plan 07 PR-4). Newest first.

## Unreleased

### 04i — stage 2 wall graph (nodes + edges after completion)
- New `src/scan2plan/geometry/wall_graph.py`: after completion, every vertical ×
  horizontal wall intersection becomes a **node** (a stub ≤ `max_extend_m` the camera
  did not cross is allowed, tagged inferred); nodes merge within `node_merge_m`;
  collinear touching segments become **one edge**; each node is typed by its incident
  directions (`L` / `T` / `cross` / `dangling_end`); **every** free end is a dangling
  flag with a location (no silent open ends). New append-only I4 keys `node_tol_m`,
  `node_merge_m`.
- `stage2_walls.json` gains `graph` (`node_count`, `edge_count`, `counts`,
  `nodes{id,uv,world,type,inferred}`, `edges{id,node_a,node_b,length_m,ci_m,provenance}`,
  `dangling_ends[]`); the SVG draws nodes (L circle, T square, cross diamond,
  dangling red ring); the CLI reports node/edge counts per type.
- Seeds: 15 / 44 / 52 nodes (11 / 44 / 62 edges). Tests `tests/test_wall_graph.py`.

### 04i — stage 2 wall completion (bridge broken lines, keep openings)
- New `src/scan2plan/geometry/wall_complete.py`, adapted from the standalone
  `wall_complete.py` prototype to our system: I4-config thresholds, typed
  dataclasses (`WallPiece`/`CompletionParams`/`CompletionResult`), deterministic.
  Every gap between collinear segments is decided once — camera crossed → **opening**
  (never bridged); furniture in front → `inferred_occluded`; short gap →
  `inferred_dropout`; else `unknown` (left open, flagged). Dangling ends extend to a
  perpendicular wall (`inferred_extension`); intervals are
  `ci_base_m + ci_per_m · assumed_length`.
- `reconstruct_walls` runs completion after merge/join; `stage2_walls.json` now
  carries `openings`, `unknown_gaps`, `completion` and per-segment `provenance`/`rule`
  (the SVG draws openings green, unknown gaps purple, inferred segments orange).
- New append-only I4 keys: `collinear_tol_m`, `occ_band_m`, `occ_min_cells`,
  `dropout_max_m`, `max_extend_m`, `perp_tol_m`, `ci_base_m`, `ci_per_m`.
- Real seeds: 11 / 37 / 41 segments, 0 / 1 / 1 openings, 1 / 16 / 14 bridge+extension
  pieces. Tests: `tests/test_wall_complete.py` (ported prototype scenarios) plus
  stage-2 completion tests.

### 04i — stage 2: multi-segment wall extraction (from stage 1 only)
- `src/scan2plan/geometry/walls.py::reconstruct_walls` consumes the frozen
  `stage1_observed.json` (**never** the raw cloud) and emits a `stage2_walls.{json,svg}`
  sidecar of **wall segments** — **no closing rectangle**, no rooms/openings (stage 3).
- Deterministic (no RNG): support gate + Manhattan frame (22.5° on `c00a170fe1`) +
  **every** histogram peak → runs ≥ `min_run_m` → merge parallel faces within
  `merge_tol_m` (thickness) → join L/T junctions (`inferred` extensions widen the
  interval). New append-only I4 keys: `merge_tol_m`, `join_tol_m`, `evidence_tol_m`.
- Replaces the min-bounding-rectangle stage 2 (git tag `stage2-rectangle`):
  evidence explained over the kept cells rises from ~4–11% (rect) to 36–59%, with
  10 / 28 / 31 segments on the three seeds. Before/after in
  `docs/plans/04i-stage2-report.md` and `bench/stage2_{before,after}/`.
- Stage-1 addition: the camera path now records `camera_start` / `camera_end`
  (marked green / red in the SVGs).
- `scan2plan run` / `ablate` write the stage-2 artifacts; docs updated
  (`docs/stage1_contract.md` §2/§6, `docs/plans/04i` §8).

### 04i cleanup — freeze stage 1, archive stage 2/3
- Tagged `stage1-frozen` (stage-1 observed evidence).
- Moved stage 2/3 (outline tracing, classification, snapping) to
  `archive/old_stage23/` for redesign; the tested wall finder
  `scan2plan.geometry.room_fit` is kept in `src/`, unused by default, excluded
  from ruff.
- `scan2plan run` now writes the stage-1 artifacts (`stage1_observed.{json,svg}`)
  and a schema-valid **stub** `plan.json` with `status="not_computed"` (new
  optional CIR field + regenerated I3). `ablate` is pending the redesign.
- Added `docs/stage1_contract.md` (every output file/field, grid sizes, every
  threshold with its config key); README notes `1a8384c3f6` is multi-room.

### 04i — three-stage room outline with explainable furniture removal
- **Stage 1 redefined as pure observed evidence** (renamed from "outline"): layered
  output, no hull/buffer/snap/interpolation — observed wall cells (with per-cell
  height-bin support), observed floor cells, camera free-space (path, optional
  ray-carve). Unknown stays blank; only confidence/range gates apply; thresholds
  logged and an unfiltered layer saved. Reports statistics only
  (`camera_inside_fraction`, evidence-vs-camera extent) and never fails.
- **"Camera inside the room" moved to a stage-3 assertion** on the final polygon
  (`camera_inside_fraction`, `assert_camera_inside`).
- **Stage 3 provenance**: every wall/corner carries `observed | inferred`; missing
  corners are inferred by extending adjacent wall lines with an interval that grows
  with the extrapolated distance.
- Ported `room_fit.py` wall logic into `src/scan2plan/geometry/wall_model.py`
  (numpy only; self-test reproduces 12.77 m² vs truth 12.80 m²).
- New `src/scan2plan/geometry/room_outline.py`: stage 1 observed outline, stage 2
  per-region classification (`noise_or_ghost` / `low_furniture` / `tall_furniture`
  / `suspected_occluder` / `wall`, each with its firing rule), stage 3 rectilinear
  final outline with per-wall state (`observed` / `partially_occluded` /
  `unobserved`).
- `scan2plan run` now writes `stage1_observed.json`, `stage2_classified.json`,
  `stage3_final.json`, plus **one SVG per stage** (`stage1_observed.svg`,
  `stage2_classified.svg`, `stage3_final.svg`), `plan.svg` and the canonical
  `plan.json` (I3-valid; rich states live in the sidecars).
- Stage-1 depth gates are config-driven (`outline.confidence_min`,
  `outline.max_range_m`); all thresholds moved into the I4 `outline` block.
- Intervals: removed the flat ±5% area and ±0.02 m door constants; wall/area CIs
  are bootstrap + odometry (quadrature), widened for occluded / weak-coverage
  walls; door-width CIs come from the gap-edge histogram.
- SVG: canvas height fits the full legend (last door lines were clipped); openings
  drawn as gaps with a swing arc.
- Known issues: areas weakly supported on the seeds (3/4 walls < 50% coverage);
  stage-2 labelling is coarse on ragged real floors. See `docs/plans/04i`.

### 04h — concave (L-shaped) room footprint
- Occupancy-grid concave footprint replaces the rectangle OBB; `single_room`
  area 38.41 -> ~19 m², doors found. OBB kept as fallback.

### 04d — stitch + drift ablation
- `scan2plan ablate` (loop-closure on/off) + SE(2) pose-graph stitch.

### 04c/04g — single-room geometry + SVG render
- Floor/ceiling planes, walls, openings, SVG plan; `scan2plan run` S1–S4.
