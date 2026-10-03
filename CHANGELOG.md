# Changelog

Honest milestone log (plan 07 PR-4). Newest first.

## Unreleased

### 04i — stage 2: deterministic wall reconstruction (from stage 1 only)
- New `src/scan2plan/geometry/walls.py::reconstruct_walls`: consumes the frozen
  `stage1_observed.json` (**never** the raw cloud) and emits a `stage2_walls.{json,svg}`
  sidecar — wall lines/segments only (no polygon/corners/openings; those are stage 3).
- Deterministic (no RNG): support gate (`min_height_bins`) + Manhattan frame + the
  per-side nearest long line beyond the camera path (ported `room_fit` logic).
- Real seeds: `c00a170fe1` 3/4 walls observed (angle 23°); `1a8384c3f6` and
  `c7d28f72c6` 4/4 (angle 87° / 28.5°), both with a `stage1_layer_capped` warning
  (stage-1's `EVIDENCE_LAYER_CAP = 60000`).
- `scan2plan run` / `ablate` now also write the stage-2 artifacts; docs updated
  (`docs/stage1_contract.md` §6, `docs/plans/04i` §8).

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
