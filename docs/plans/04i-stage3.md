# 04i — Stage 3: rooms, closed polygons, per-room measurements

```
Owner:           04c (refines S3 internals; no frozen-interface change)
Provides:        stage3_rooms.json, populated plan.json (I3), plan.svg
Consumes:        I2 (CIR), I4 (config `outline`), I6 (Measurement), I7 (frames), I8 (recon)
Must-not-change: I1–I9 (plan.json stays I3-valid; rich state lives in the sidecar)
Depends-on:      04b (recon), 04c (S3), 04h (footprint), 04i stages 1-2
```

Stage 3 (`scan2plan.geometry.rooms.build_stage3`) consumes the **frozen** stage-1
evidence and the stage-2 wall graph **only** (plus config, the floor height and the
cloud for the ceiling) and emits closed, dimensioned rooms. Pure geometry (no vision
model), deterministic (fixed ordering, ties by position, fixed RNG seed), byte
reproducible. `scan2plan run` writes `stage3_rooms.json`, a populated schema-valid
`plan.json` (`status="computed"`) and `plan.svg`.

## Pipeline

- **3a closure** (`close_walls`): greedy, cost-ordered. Each dangling end yields
  `extend_perp` / `join_end` / `snap_boundary` candidates; `closure_cost` scores
  `length - closure_bonus_m·(supported length) + closure_floor_penalty·(length on free
  floor)`; a candidate crossing the camera path (and not an opening) is **forbidden**
  (rule 6). Candidates are re-evaluated after each accept; accepted pieces are tagged
  `inferred_closure` with `assumed_length_m`. `plan_score` = the summed accepted costs
  (the future local-search objective; the search is not implemented).
- **3b regions** (`build_regions` / `split_regions`): the observed-footprint domain
  (wall lines + floor/camera evidence bins, filled + hole-filled) is flood-filled with
  the closed walls as barriers. Regions are split at **doorway-shaped waists**
  (`waist_min_m`..`waist_max_m`, a strong isolated pinch that opens to a real room),
  producing `inferred_opening` records. Regions with no camera cell are
  `unobserved_enclosed` (no dimensions), per the spec. A waist is passable, so both
  halves inherit the parent's visited/camera status.
- **3c per-room geometry**: an orthogonal polygon from the region boundary, **offset-
  snapped** (wall edges to their exact wall; floor edges to the `min_step_m` grid,
  which collapses staircase noise), wall lengths node-to-node, shoelace area, and
  Monte-Carlo intervals (fixed seed, `mc_samples`) for area and every wall length
  (observed half-width = `max(wall ci, odometry_ci_frac·length)`; inferred =
  `ci_base_m + ci_per_m·length`). The point value is the best-estimate polygon.
- **3d ceiling**: histogram peak of in-room cells above `floor + ceiling_min_above_floor_m`;
  a plane is accepted only if its band holds >= 10% (and >= 50) of the above-threshold
  cells. Otherwise the room is `unmeasured` with the `prior` interval 2.4-2.7 m.
- **3e openings / adjacency**: stage-2 camera-crossed gaps + room-split waists, each
  with width + type (`door`), host wall, and the two rooms it joins; adjacency from
  those openings.

## Invariants (run after every capture — fail loudly)

`scan2plan.geometry.invariants.check_stage3_invariants` runs after stage 3 on every
`run` / `ablate`; each invariant prints its values and a failure exits non-zero
(the plan is still written for inspection). Skipped (`ok=null`) only when no rooms
were computed.

| Invariant | Rule | Config |
|---|---|---|
| `no_overlap` | room polygons simple; total pairwise intersection area <= tol | `overlap_tol_m2` |
| `min_room` | every room area >= A and inscribed-circle radius >= R | `min_room_area_m2`, `min_room_inradius_m` |
| `coverage` | camera-visited cells inside a room / opening / enclosed region >= share | `coverage_min` |
| `camera_inside` | every camera position in a room, an opening or an `open_space` | — |
| `render_clip` | walls drawn only as clipped graph edges; no span beyond its end nodes | `node_tol_m`, `node_merge_m` |
| `ceiling_sanity` | `measured` needs >= N cells, >= 20% footprint, height in 2.1-4.0 m; spread > 0.3 m flags `inconsistent_ceiling` | `ceiling_min_cells`, `ceiling_min_footprint_frac`, `ceiling_height_low_m`, `ceiling_height_high_m`, `ceiling_spread_max_m` |

The per-invariant values are recorded in `stage3_rooms.json` under `invariants`
(and the stage-1 floor/ceiling reference under `stage1_reference`).

## Thresholds (all in the I4 `outline` block — uncalibrated, plan 04f/08)

| Key | Default | Why |
|---|---|---|
| `closure_max_m` | 2.50 | longest accepted closure run |
| `closure_wall_tol_m` | 0.05 | "faint wall cells along the candidate" = `evidence_tol_m` |
| `closure_bonus_m` | 1.00 | removes cost per metre of supported line |
| `closure_floor_penalty` | 1.00 | adds cost per metre crossing free floor |
| `waist_min_m` / `waist_max_m` | 0.60 / 2.50 | doorway width band (matches the opening cap) |
| `room_grid_m` | 0.02 | region raster (2 cm, per spec) |
| `room_min_area_m2` | 0.50 | drop tiny regions |
| `mc_samples` | 500 | Monte-Carlo draws |
| `ceiling_min_above_floor_m` | 2.00 | below this is furniture/wall band, not a ceiling |
| `ceiling_bin_m` | 0.02 | ceiling histogram bin |
| `ceiling_prior_low_m` / `_high_m` | 2.40 / 2.70 | prior interval when the ceiling is not seen |
| `min_step_m` | 0.30 | floor-edge snap grid (staircase collapse) |
| `min_room_area_m2` | 2.00 | invariant: smallest accepted room |
| `min_room_inradius_m` | 0.60 | invariant: smallest accepted room width |
| `coverage_min` | 0.95 | invariant: camera cells inside regions |
| `ceiling_min_cells` | 200 | invariant: min near cells for a `measured` ceiling |
| `ceiling_min_footprint_frac` | 0.20 | invariant: min footprint share for a `measured` ceiling |
| `ceiling_height_low_m` / `_high_m` | 2.10 / 4.00 | invariant: plausible measured band |
| `ceiling_spread_max_m` | 0.30 | invariant: across-room spread flag |
| `ceiling_global_tol_m` | 0.30 | per-room peak vs the stage-1 global ceiling |
| `overlap_tol_m2` | 0.0001 | invariant: total pairwise room overlap (1 cm²) |

## Fix log (plan 04i fix loop — one commit per step)

1. **Overlap + render clipping.** `simplify_polygon` now collapses consecutive
   parallel edges (the bow-tie source in `_corners_from_offsets`) and falls back to
   the valid raw region boundary when a snapped loop is still not simple;
   `resolve_overlaps` makes room polygons simple and disjoint (each intersection is
   assigned to the room whose region owns more of it; the other is clipped and its
   edges/area/CI re-derived) and is reported in `stage3_rooms.json`
   (`overlap_resolved`). `render/svg.py::clipped_wall_lines` draws every wall only as
   a segment clipped to its graph nodes; `plan.svg` now draws those walls (observed
   solid, inferred dashed).

2. **Minimum room rule.** `apply_min_room_rule` merges a region that fails
   `min_room_area_m2` (2.0) or `min_room_inradius_m` (0.6) into the neighbour it
   shares the longest boundary with (smallest failing region first, ties by index),
   else labels it `non_room_fragment` (reported in `stage3_rooms.json`
   `non_room_fragments` / `min_room_merges`). A polygon-level guard applies the same
   gate after snapping. Rooms are never emitted below the gate.

3. **Ceiling plane selection.** `room_ceiling` now takes the stage-1 global ceiling
   plane (`ceil_y`, previously never passed): candidate peaks are the in-room
   height-histogram maxima, and when a global ceiling exists only peaks within
   `ceiling_global_tol_m` of it are considered (a wardrobe top / sloped surface can
   no longer win). A candidate is accepted only with >= `ceiling_min_cells` cells,
   >= `ceiling_min_footprint_frac` of the room footprint and a height in
   `[ceiling_height_low_m, ceiling_height_high_m]`; otherwise the room reports the
   prior. The candidate table (height / cells / footprint / accepted) is recorded in
   each room's `ceiling`. Across-room spread > `ceiling_spread_max_m` flags
   `inconsistent_ceiling`.

4. **Coverage.** `build_regions` now carves the full stage-1 camera free-space layer
   out of the wall barrier (a wall cannot cover walked space) and counts it as
   visited, so a region the camera walked through becomes a room; a region with a
   camera is never `discarded` (the min-room rule merges it instead). Each room
   polygon is made a **superset of its region** (union of the snapped polygon with the
   exact region boundary, else the raw boundary, else the exact raster outline), so
   the walked cells lie inside the emitted polygons. Edges with no matched wall are
   tagged `inferred_closure` (wide interval) instead of `prior`. Two supporting bug
   fixes: `region_inradius` now pads its EDT mask (it over-estimated badly, e.g. a
   1 m square read 1.40 m), and `split_regions` is depth-first and never drops a
   region when its guard trips.

## Known limitations (honest; rule 7)

- The footprints are ragged: stage-1 floor evidence is sparse (10 cm cells, and the
  large captures are capped at 60k wall cells), so the region boundary is a staircase;
  `min_step_m` regularises it but the polygons still carry many corners.
- The `single_scan_floor_only` (multi-room) capture resolves only **2 rooms**; the rest
  of the footprint floods into `unobserved_enclosed` because the region is disconnected
  by the capped/sparse evidence, not because no camera visited it. Reported, not hidden.
- Ceiling detection on the seeds is unreliable (a low wall-band peak / a high noise
  plane); the ceiling is marked uncalibrated and `unmeasured` is preferred via the
  support gate.
- The closure greedy is first-fit by cost; no local search yet (hook: `plan_score`).