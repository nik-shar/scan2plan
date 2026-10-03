# Changelog

Honest milestone log (plan 07 PR-4). Newest first.

## Unreleased

### 04i — three-stage room outline with explainable furniture removal
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
