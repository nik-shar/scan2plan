# 04i — Three-stage room outline with explainable furniture removal

```
Owner:           04c (refines S3 internals; no frozen-interface change)
Provides:        stage JSONs (stage1_observed / stage2_classified / stage3_final)
Consumes:        I2 (CIR), I4 (config `outline`), I6 (Measurement), I7 (frames), I8 (recon)
Must-not-change: I1–I9 (plan.json stays I3-valid; rich states live in sidecars)
Depends-on:      04b (recon), 04c (S3), 04h (footprint)
```

## 1. Goal

Replace the S3 outline step with a three-stage, explainable process so furniture and
sensor ghosts are removed **with the rule that removed them**, and every emitted
number is a wall that is long, aligned, height-supported, beyond the camera path,
and reported with a bootstrap + odometry interval. Ported from the tested
`room_fit.py` reference logic (now `geometry/wall_model.py`).

## 2. Stages

- **Stage 1 (observed evidence):** pure layers, no hull/buffer/snap/interpolation.
  S2 drops depth with `confidence < confidence_min` and `range > max_range_m`;
  stage 1 then emits `stage1_observed.json` + `stage1_observed.svg` with three
  layers — **observed wall cells** (each with a per-cell height-bin *support*
  count), **observed floor cells**, and **camera free-space** (path, optionally
  ray-carved with `ray_carve`). Unknown area stays blank. It reports statistics
  only (`camera_inside_fraction`, evidence vs camera extent) and never fails;
  thresholds are logged in the payload and an **unfiltered** layer (gates off) is
  saved for comparison.
- **Stage 2 (classify):** every region labelled exactly once with the firing rule —
  `noise_or_ghost`, `low_furniture`, `tall_furniture`, `suspected_occluder`,
  `wall` — as `{label, rule, params, polygon_xz, area_m2}` in
  `stage2_classified.json` + `stage2_classified.svg` (walls black, removed dashed
  grey, occluders orange).
- **Stage 3 (final):** the rectilinear room, built from wall items + the observed
  floor (stage 3 may interpolate/snap), 4–8 edges. Every element carries
  **provenance = `observed` | `inferred`**; a corner is `observed` when an observed
  wall cell lies within `infer_tol_m`, else `inferred` by extending adjacent wall
  lines with an interval that grows with the extrapolated distance
  (`inferred_ci_per_m`). A side with no fitted wall line is inferred and flagged.
  The old "camera must be inside the room" assumption is now an explicit **stage-3
  assertion** (`camera_inside_fraction`, `assert_camera_inside`). Outputs:
  `stage3_final.json` + `stage3_final.svg`, `plan.json` (I3-valid), `plan.svg`.

Each stage therefore has its **own SVG** for side-by-side inspection (04i).

## 3. Thresholds (all in I4 `outline`; rationale)

| Key | Default | Why |
|---|---|---|
| `confidence_min` | 1 | ARKit "medium or better" (0=low,1=medium,2=high) |
| `max_range_m` | 8 | drop far returns before they inflate the fit |
| `cell_m` | 0.02 | room_fit grid; walls are dense, 2 cm resolves lines |
| `height_bins` / `min_height_bins` | 10 / 4 | a wall spans many heights; furniture/ghost does not (room_fit) |
| `wall_min_m` / `wall_max_m` | 0.25 / 1.9 | skip skirting and the ceiling join |
| `min_run_m` | 1.2 | reject short wall-like things (0.7 m fridge) |
| `run_gap_m` | 0.10 | a doorway does not split a wall run |
| `cam_margin_m` | 0.10 | wall must be beyond the camera path |
| `min_peak_frac` | 0.15 | ignore weak histogram peaks |
| `furniture_max_m` | 1.0 | "low furniture" = only below 1 m |
| `occluder_inset_m` | 0.3–0.7 | occluder face sits this far in front of the real wall |
| `min_step_m` | 0.3 | steps shorter than this merge into their neighbour |
| `max_edges` | 8 | simple room -> 4-8 edges |
| `odometry_ci_frac` | 0.01 | scale/drift term (1% of length) added in quadrature |
| `weak_coverage_frac` | 0.5 | < 50% support -> widen interval |
| `occluded_ci_scale` | 2.0 | occluded wall interval multiplier |
| `bootstrap_n` | 200 | wall-cell resamples for the position/area CI |
| `evidence_bin_m` | 0.10 | stage-1 floor/free-space cell size |
| `floor_band_m` | 0.08 | floor slab thickness for the observed-floor layer |
| `ray_carve` | false | optionally carve free-space cells along camera->point rays |
| `free_stride` | 25 | point subsample for ray carving |
| `save_unfiltered` | true | also emit `points_unfiltered.npz` + unfiltered evidence layer |
| `infer_tol_m` | 0.20 | a corner within this of observed wall evidence is `observed` |
| `inferred_ci_per_m` | 0.05 | interval growth per metre of extrapolation (inferred corners) |
| `assert_camera_inside` | false | when true, raise if the camera path leaves the stage-3 polygon |

## 4. Intervals

Wall length = `fit_room` bootstrap CI (both wall positions) **⊕** `odometry_ci_frac ·
length` in quadrature, ×`occluded_ci_scale` when `partially_occluded` or coverage <
`weak_coverage_frac`. Area likewise. The flat `AREA_CI_REL = 0.05` and constant
`OPENING_CI_M = 0.02` are removed; door-width CIs come from the gap-edge histogram
(`bin_w·(0.5 + 0.5·(1 - emptiness))`).

## 5. Results (three seeds)

| Capture | travel | stage1 | stage3 | edges | removed (by label) | warnings |
|---|---|---|---|---|---|---|
| `c00a170fe1` | 14.1 m | 23.0 m² | 23.7 m² | 8 | low_furniture 2, tall_furniture 1, noise_or_ghost 8 | weak coverage u_min,v_min,v_max |
| `1a8384c3f6` | 53.8 m | 71.3 m² | 64.3 m² | 8 | noise_or_ghost 20 | weak coverage u_min,u_max,v_min |
| `c7d28f72c6` | 98.8 m | 83.4 m² | 89.6 m² | 8 | low_furniture 1, tall_furniture 4, noise_or_ghost 4 | weak coverage; **suspected_occluder v_max** |

Every `plan.json` passes `scan2plan validate`. `room_fit` self-test: **12.77 m²**
(truth 12.80); `--wardrobe`: area fails (11.04 m²) and the wardrobe is flagged a
`suspected_occluder` with a widened interval.

## 6. Cases that still look wrong (honest)

- **Areas are large and weakly supported.** All three seeds report `weak coverage`
  on 3 of 4 sides (< 50%); the fitted wall lines sit well outside the observed
  floor, so stage 3 is closer to the rectangle than to the true outline. The
  intervals are honest (widened) but the central value is not yet trustworthy.
- **Stage-2 is coarse.** Wall regions are labelled from 0.10 m component boxes; on
  ragged real floors nearly everything falls to `noise_or_ghost` (20/20 on
  `1a8384c3f6`). It is diagnostic, not yet a precise segmenter.
- **Mirror attribution unknown on real data.** The synthetic mirror ghost is
  rejected by the height-support test (unit-tested); for the three real captures a
  mirror cannot be confirmed without inspecting the footage, so the `beyond_nearest
  _wall_line` (8 / 20 / 4 regions) counts are reported as-is, not attributed.
- **Stage-3 `state` can be inert** when the observed polygon does not reach the
  fitted wall lines: edges remain `step` and no wall is flagged even though a
  global weak-coverage warning fires.

## 7. Tasks / commits

G-10 port (`wall_model`) · G-11 config (`outline`) · G-12 stage driver · G-13 CLI +
stage JSONs · G-14 SVG fixes · G-15 tests · G-16 docs. One commit per stage.

## 8. Stage-2 redefinition (implemented)

Stage 2 was redefined from *classification* to **deterministic wall
reconstruction** (agreed boundary; stage 3 — closing/classification — is still
being redesigned):

- **Input = the frozen stage-1 artifact only** (`stage1_observed.json`); stage 2
  never reads the raw cloud, so it is a pure, byte-reproducible function of stage 1.
- **Output = a sidecar** (`stage2_walls.json` + `stage2_walls.svg`): wall records
  only. There is **no** polygon, corner, opening or measurement (those stay in
  stage 3), and no RNG (bootstrap intervals are deferred to stage 3/uncertainty).
- **Pipeline** (`src/scan2plan/geometry/walls.py::reconstruct_walls`):
  1. support gate (`min_height_bins`) — drop cells seen in too few height bins;
  2. Manhattan frame from histogram sharpness;
  3. per side, the nearest well-supported *long* line beyond the camera path
     (`cam_margin_m`, `min_run_m`, `run_gap_m`, `min_peak_frac`, `peak_smooth`);
  4. clip each line to the room extent -> length/coverage/support.
  It ports the tested `room_fit`/`wall_model` primitives; every threshold is an
  existing I4 `outline` key (no new config, no interface change).

**Explainability.** Each wall carries the rule that selected it
(`nearest_supported_long_line_beyond_camera`); every dropped cell carries
`support_below_min_height_bins`; a side with no line is `unobserved` (never
guessed); weak coverage is warned, not hidden.

**Measured (three seeds).**

| Capture | angle | cells kept/input | walls observed | warnings |
|---|---|---|---|---|
| `c00a170fe1` | 23.0° | 2,814 / 15,823 | 3/4 (`v_min` unobserved) | weak coverage `v_max` |
| `1a8384c3f6` | 87.0° | 9,219 / 76,487 | 4/4 | layer capped; weak `u_min,u_max,v_min` |
| `c7d28f72c6` | 28.5° | 14,380 / 101,669 | 4/4 | layer capped; weak `u_min,v_min,v_max` |

**Known limitation (honest).** Stage 1 caps each layer at `EVIDENCE_LAYER_CAP =
60,000` cells, so on the two large seeds stage 2 fits a deterministic subsample
(~78% / ~59% of wall cells) and warns `stage1_layer_capped`. This is fix-loop
material (plan `06`) if it binds a wall gate; the cap lives in the frozen stage-1
contract, so stage 2 reports it rather than reaching around it.

**Tests** `tests/test_stage2_walls.py`: four-wall recovery + lengths, support-gate
drop count, inset short-run rejection, unobserved side, no polygon/openings in the
payload, byte-identical determinism, degenerate/empty inputs, CLI writes the
sidecar.

