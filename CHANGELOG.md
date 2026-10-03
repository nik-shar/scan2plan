# Changelog

Honest milestone log (plan 07 PR-4). Newest first.

## Unreleased

### 04i — fix 3: ceiling plane selection (global reference + support gates)
- `build_stage3`/`_make_room` now receive the stage-1 global ceiling plane (`ceil_y`)
  and pass it to `room_ceiling` (it was computed but never passed).
- `room_ceiling` considers every in-room height-histogram peak, restricted to peaks
  within `ceiling_global_tol_m` (0.30) of the global ceiling when one exists; a
  candidate is accepted only with >= `ceiling_min_cells` (200) cells, >=
  `ceiling_min_footprint_frac` (0.20) footprint coverage and a height in
  `[2.1, 4.0]` m, else the room is `unmeasured` with the prior. The candidate table
  is recorded per room for diagnosis.
- Seeds: `c00a170fe1` room_4's 2.01 m furniture-top peak is now rejected
  (`accepted=false`, height < 2.1) -> unmeasured prior; `c7d28f72c6` no longer picks
  the 3.08 m peak (filtered by the 2.438 m reference) - room_2 measures 2.27 m and
  room_1's partial 2.47 m plane is honestly rejected on footprint. `ceiling_sanity`
  passes on all three seeds. Test added to `tests/test_rooms.py`.

### 04i — fix 2: minimum room rule (merge small regions / non_room_fragment)
- New `rooms.apply_min_room_rule` (region level, deterministic): a region that fails
  `min_room_area_m2` (2.0 m²) or `min_room_inradius_m` (0.6 m) is merged into the
  neighbour it shares the longest boundary with; with no neighbour - or if the merge
  still fails - it becomes `non_room_fragment`. A polygon-level guard applies the
  same gate after snapping. Reported in `stage3_rooms.json`
  (`non_room_fragments`, `min_room_merges`).
- Seeds: `c00a170fe1` 7 -> 5 rooms (smallest 0.27 m² gone), `1a8384c3f6` 2 -> 1 room
  + 1 fragment. `min_room` now passes; coverage improves as a side effect.

### 04i — fix 1: room-polygon overlap/validity + wall render clipping
- All 9 seed room polygons were self-intersecting (bow-tie): `simplify_polygon` now
  collapses consecutive parallel edges before rebuilding corners (the
  `_corners_from_offsets` fallback that produced bow-ties) and falls back to the
  valid raw region boundary if a snapped loop is still not simple.
- New `rooms.resolve_overlaps`: polygons are made simple and pairwise disjoint
  (intersections assigned to the region that owns more of them; the other polygon is
  clipped and its edges/area/CI re-derived). Reported in `stage3_rooms.json`
  (`overlap_resolved`). `no_overlap` now passes on all three seeds.
- New `render/svg.py::clipped_wall_lines`: walls are drawn only as segments clipped
  to their graph nodes; `plan.svg` draws them (observed solid, inferred dashed) and
  the dead `return` in `render_plan_svg` is removed. `render_clip` passes on all three.
- `tests/test_invariants.py` render-clip case unchanged; suite green.

### 04i — stage-3 invariant checks (fail loudly)
- New `src/scan2plan/geometry/invariants.py`: `check_stage3_invariants` runs after
  every `run` / `ablate` and prints six invariants with their values, exiting
  non-zero on violation (`plan.json` is still written for inspection; skipped when
  no rooms are computed). `no_overlap` (simple polygons, total pairwise area <=
  `overlap_tol_m2`), `min_room` (area/inradius), `coverage` (camera cells inside
  rooms/openings/enclosed), `camera_inside`, `render_clip` (wall spans clipped to
  graph nodes), `ceiling_sanity` (cells + footprint + height band; across-room
  spread flags `inconsistent_ceiling`). Values are recorded in `stage3_rooms.json`
  (`invariants`, `stage1_reference`).
- New append-only I4 keys (uncalibrated): `min_room_area_m2`, `min_room_inradius_m`,
  `coverage_min`, `ceiling_min_cells`, `ceiling_min_footprint_frac`,
  `ceiling_height_low_m`, `ceiling_height_high_m`, `ceiling_spread_max_m`,
  `ceiling_global_tol_m`, `overlap_tol_m2`. See `docs/plans/04i-stage3.md`.
- Diagnosis on the three seeds: 9 of 9 room polygons are self-intersecting (bow-tie),
  rooms as small as 0.27 m² survive, coverage 0.09-0.73 (camera cells leak into
  wall barriers), walls over-extend their graph nodes by 3.5-20 m, and `2.01 m`
  ceilings are accepted from furniture tops. Tests `tests/test_invariants.py` (10).

### 04i — stage 3: rooms, closed polygons, per-room measurements
- New `src/scan2plan/geometry/rooms.py::build_stage3` (pure geometry, deterministic):
  greedy cost-ordered **closure** (`closure_cost`/`plan_score`, camera-crossing
  forbidden), **regions** flood-filled from the observed footprint with **waist**
  splits (`inferred_opening`) and `unobserved_enclosed` regions, per-room **polygon**
  (offset-snapped, L-shapes supported) with node-to-node wall lengths, shoelace area
  and **Monte-Carlo** intervals, **ceiling** (histogram peak, else an `unmeasured`
  prior), **openings/adjacency**.
- `scan2plan run` now writes `stage3_rooms.json`, a populated I3-valid `plan.json`
  (`status="computed"`: rooms/surfaces/openings/measures) and `plan.svg`
  (`render/plan_svg.py`: observed solid, inferred dashed per provenance, opening arcs,
  area labels, scale bar, hatched unobserved). No I3 schema change (existing fields).
- New append-only I4 keys (uncalibrated, plan 04f/08): `closure_max_m`,
  `closure_wall_tol_m`, `closure_bonus_m`, `closure_floor_penalty`, `waist_min_m`,
  `waist_max_m`, `room_grid_m`, `room_min_area_m2`, `mc_samples`,
  `ceiling_min_above_floor_m`, `ceiling_bin_m`, `ceiling_prior_low_m`,
  `ceiling_prior_high_m`. Every element carries provenance (`observed` /
  `inferred_*` / `prior`). See `docs/plans/04i-stage3.md`.
- Tests `tests/test_rooms.py` (11): synthetic rect + L-shape area/walls, determinism
  (byte-identical), ceiling prior, closure-cost rules, Monte-Carlo coverage (~95%).

### 04i — stage 2 cleanup (opening cap, wall merge, evidence split)
- **Opening-width cap** (I4 `open_min_m` 0.5 / `open_max_m` 2.5): a camera-crossed
  gap narrower than `open_min_m` is a **dropout**, wider than `open_max_m` is a new
  **`open_space`** class (a walk-through, not an opening); only 0.5-2.5 m gaps are
  `openings`. `stage2_walls.json` gains `open_spaces[]` (SVG teal).
- **Wall merge** (`geometry/wall_complete.py::merge_wall_pieces`): after completion,
  parallel same-axis pieces whose offsets are within `merge_tol_m` (0.25) and whose
  spans overlap (or abut with matching provenance) collapse into one wall, recording
  `thickness_m`; a completion bridge that only abuts keeps its own provenance. The
  graph is built on the merged walls; **all** nodes within `node_merge_m` (0.10) —
  line ends included — are merged before the nodes are re-typed (L/T/cross/dangling).
- **Length reporting**: `stage2_walls.json` `lengths` = `observed_length_m`,
  `inferred_length_m`, `longest_inferred_run_m`, and a flag when any inferred run
  exceeds `max_extend_m` (1 / 11 / 6 flagged runs on the three seeds).
- **Evidence split**: `evidence` now partitions every wall cell into
  `wall_like_explained` / `dense_blobs` / `residual_noise` (density gate
  `blob_bin_m` 0.10, `blob_min_cells` 6); the SVG shades wall-like grey, dense blobs
  orange, residual noise pale red.
- **Node/cross report**: a `merge` block reports segments / nodes / crosses
  before→after. Crosses do **not** drop on the seeds (4→4, 6→6) and are reported
  honestly: they are genuine 4-way meetings of interior walls (near-parallel lines
  0.31 m apart exceed the 0.25 m merge tolerance), not double-face artifacts.
- New append-only I4 keys `open_min_m`, `open_max_m`, `blob_bin_m`, `blob_min_cells`.
  Tests: `test_wall_complete.py` (+7), `test_stage2_walls.py` (+4).

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
