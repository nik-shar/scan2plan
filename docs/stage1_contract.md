# Stage 1 — Observed-evidence contract

**Status:** frozen at tag `stage1-frozen`. Stages 2/3 (outline tracing,
classification, snapping) were moved to `archive/old_stage23/` for redesign;
`scan2plan run` emits stage-1 artifacts plus a stub `plan.json`.

Stage 1 is **pure evidence**: no hull, buffer, snapping or interpolation (those
belong to stage 3). Only two filters apply, and they are applied upstream in S2.

## 1. Inputs

| Input | Source | Gate (config key, default) |
|---|---|---|
| world point cloud | S2 recon (`recon/points.npz`) | `outline.max_range_m` = 8 m (drop far returns) |
| confidence mask | `confidence/*.png` | `outline.confidence_min` = 1 (ARKit medium-or-better) |
| unfiltered cloud | `recon/points_unfiltered.npz` (gates off) | written when `outline.save_unfiltered` = true |
| camera path | per-frame `T_wc` centres | — |
| floor / ceiling Y | `horizontal_planes` (2% Y fallback if none) | — |

## 2. Output files

### `stage1_observed.json` (sidecar; not schema-frozen)

| Field | Meaning |
|---|---|
| `name` | `"observed evidence"` |
| `params` | every threshold that was used (below) |
| `camera_travel_m` | total camera path length (m) |
| `camera_xz` | downsampled camera path (≤ 200 points) |
| `camera_start` / `camera_end` | first / last camera position `[x, z]` (stage-1 addition; the SVG marks them green / red; `null` with no poses) |
| `layers.wall_cells[]` | wall-band cells `{x, z, support}` (support = # height bins occupied) |
| `layers.floor_cells[]` | floor-slab cells `[x, z]` |
| `layers.camera_free_space[]` | camera-path cells (+ ray-carved if `ray_carve`), `[x, z]` |
| `layer_counts` | `{wall_cells, floor_cells, camera_free_space}` (pre-cap counts) |
| `statistics.camera_inside_fraction` | fraction of camera positions over floor/wall evidence (±1 cell) |
| `statistics.evidence_extent_m` / `camera_extent_m` | XZ extents of evidence / camera path |
| `statistics.camera_exceeds_evidence` | bool: camera goes outside the observed evidence |
| `unfiltered` | same wall/floor layers computed with the gates **off** (+ counts) |
| `warnings` | e.g. layer cap hit; degenerate-cloud note |

Every layer list is capped at `EVIDENCE_LAYER_CAP = 60000` cells (deterministic
subsample) to keep the sidecar readable; `layer_counts` always reports the true
count.

### `stage1_observed.svg`
A rasterised view (embedded PNG): wall cells (grey, darker = more support), floor
cells (light blue), camera free-space (light green), camera path (blue line),
plus a legend with the layer counts, bin size, camera travel and
`camera_inside_fraction`. Unknown area stays blank.

### `plan.json` (stub)
Schema-valid against I3 (`scan2plan validate`), `status = "not_computed"`, empty
`rooms/surfaces/openings/measures`, with `session + frames + recon + provenance`.

## 3. Grid sizes

| Layer | Bin | Config key |
|---|---|---|
| wall cells | **2 cm** | `outline.cell_m` |
| floor cells | **10 cm** | `outline.evidence_bin_m` |
| camera free-space | **10 cm** | `outline.evidence_bin_m` |
| wall band (vertical) | 10 equal height bins over `[wall_min_m, wall_max_m]` | `outline.height_bins` |

## 4. Thresholds (all in the I4 `outline` block)

| Config key | Default | Role in stage 1 |
|---|---|---|
| `confidence_min` | 1 | drop depth below ARKit "medium" |
| `max_range_m` | 8.0 | drop returns beyond 8 m |
| `cell_m` | 0.02 | wall-cell bin size |
| `height_bins` | 10 | vertical bins across the wall band |
| `min_height_bins` | 4 | *(classification, stage 2)* – recorded only |
| `wall_min_m` | 0.25 | wall band bottom above the floor |
| `wall_max_m` | 1.9 | wall band top when there is no ceiling |
| `evidence_bin_m` | 0.10 | floor/free-space bin size |
| `floor_band_m` | 0.08 | floor slab half-thickness |
| `ray_carve` | false | carve free-space along camera→point rays |
| `free_stride` | 25 | point subsample for ray carving (deterministic) |
| `save_unfiltered` | true | also emit the unfiltered cloud + layer |

Thresholds that only affect stage 2/3 (`min_run_m`, `cam_margin_m`,
`occluder_inset_m`, `min_step_m`, `infer_tol_m`, `inferred_ci_per_m`,
`weak_coverage_frac`, `occluded_ci_scale`, `assert_camera_inside`, …) remain in
the config but are unused until the redesign lands.

## 5. Guarantees

1. **Deterministic** — same points + camera + config ⇒ byte-identical JSON
   (no RNG; layer lists sorted).
2. **Never fails** — degenerate input yields empty layers + a warning; the stub
   `plan.json` still validates.
3. **No vision model** touches the numbers; stage 1 is pure geometry.
4. **Layers only** — no closed polygon, hull or interpolation is produced.

## 6. Consumer: stage 2 — multi-segment wall extraction

Stage 2 (`scan2plan.geometry.walls.reconstruct_walls`, plan 04i §8) consumes **this
artifact only** — `layers.wall_cells` (`x`/`z`/`support`), `layers.floor_cells`, and
`camera_xz` / `camera_start` / `camera_end` — and emits the `stage2_walls.{json,svg}`
sidecar. It never re-reads the raw cloud, so *this artifact + config fully determine
it* (byte-reproducible). It applies the `min_height_bins` support gate, takes **every**
histogram peak, keeps contiguous runs >= `min_run_m`, merges parallel segments within
`merge_tol_m`, joins L/T junctions within `join_tol_m`, and finally **completes** the
walls (`geometry/wall_complete.py`): a gap the camera crossed becomes an opening,
furniture-in-front or a short dropout is bridged, and dangling ends extend to a
perpendicular wall. It reports `evidence_explained` (share of wall cells within
`evidence_tol_m` of a segment).

Because each layer is capped here at `EVIDENCE_LAYER_CAP`, stage 2 warns
`stage1_layer_capped` and fits the deterministic subsample when the true count
(`layer_counts`) exceeds the serialised list length.
