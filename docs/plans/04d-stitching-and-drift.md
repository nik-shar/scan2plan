# 04d — Multi-room Stitching, Drift & Ablation

```
Owner:           04d
Provides:        stitch{} in I2
Consumes:        rooms[]/surfaces[] (04c), I8 (recon), I6
Must-not-change: I1, I2, I3, I8, I6
Depends-on:      04a, 04b, 04c
```

The **product surface** (OUT-2) and the hardest gates (**G-PSTITCH**, **G-DRIFT**).

## 1. Problem

Each room is reconstructed locally. Stitching must place every room in one plan with **correct adjacency**,
**no overlaps**, and **honest handling of accumulated drift** on the multi-room capture.

## 2. Stitch pipeline

1. **Room graph.** Nodes = rooms. Candidate edges = shared **connectors** (doors/passages) found in `04c`.
2. **Connector matching.** A door between room A and B gives a relative transform. Match opening polygons
   by width/height similarity + wall normal opposition.
3. **Loop closure.** Detect revisits (same room from different pass, or corridors revisited) via place/feature
   matching → extra relative constraints. Rejects "poses as-is".
4. **Pose-graph optimization.** SE(2) (plan-view) optimize over all relative edges → globally consistent
   transforms. Default `scipy.optimize.least_squares`; optional GTSAM.
5. **Plane anchoring.** After optimization, snap shared walls to a common plane and align all room floors to
   one z; resolve remaining overlaps by **polygon projection** (Shapely `unary_union`/clipping).
6. **Overlap check.** `overlap_ok` = true iff interior polygons are pairwise disjoint (tolerance).
7. **Emit** `stitch{plan_frame, room_transforms, edges, closures, overlap_ok, ablation}`.

## 3. Drift policy (G-DRIFT: "poses used as-is" = automatic fail)

- **No tier may consume raw poses as final geometry.** LiDAR odometry = **init only**.
- Method ladder, applied in order: (a) loop closure, (b) pose-graph optimization, (c) plane-anchored correction.
- Report must state **which** method applies to the multi-room capture.

## 4. Ablation harness (required by G-DRIFT)

- CLI: `scan2plan ablate --capture <id> --feature loop_closure`.
- Emits two footprints from the **same code path** with the feature `on`/`off`.
- Stored in `stitch.ablation.{loop_closure_on,off}` and rendered side by side.
- Metric = stitched footprint area (m²) and closure of the loop (gap before/after).

## 5. Photo-tier stitching (G-PSTITCH: single-room-only fails)

- Per-room photo folders → per-room recon (`04b`) → stitch **without poses**:
  connector matching + appearance matching between folder boundary images.
- Enforce **no room overlap**; footprint within **±8%** (CI from `04f`).

## 6. Tasks

| ID | Task | Done when | Status |
|---|---|---|---|
| S-1 | Room graph + connector matching | adjacency found on multi-room set | ✅ `stitch/graph.py`; wired via `geometry/plan_geometry.py` (paired openings) |
| S-2 | Loop-closure detection | closures reported with evidence | ✅ `stitch/closures.py` (deterministic ICP) |
| S-3 | SE(2) pose-graph optimizer | consistent plan; residuals reported | ✅ `stitch/optimize.py` |
| S-4 | Plane anchoring + overlap resolution | `overlap_ok=true` on benchmark | 🟡 overlap gate ✅; plane-anchoring fallback pending |
| S-5 | Ablation CLI + rendering | on/off footprints differ and are saved | ✅ `stitch/wire.py` + `ablate` + `ablation.svg` |
| S-6 | Photo-folder stitch path | folders → one plan, no overlap | ⬜ pending (needs 04b photo recon) |

Wired into the pipeline by `src/scan2plan/stitch/wire.py` (`stitch_plan`,
`rooms_connected`, `ablation_transforms`); `scan2plan run` populates `cir.stitch`,
`scan2plan ablate` writes `ablation.svg`. Note: a single capture reconstructs all
rooms in one shared frame, so the ablation is `on == off` when no revisit exists —
reported honestly, not hidden.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Wrong connector match → bad stitch | require width/normal agreement; keep top-k, optimize globally |
| Drift without revisits | closer capture spacing (protocol); plane anchoring fallback |
| Overlap from scale error | snap to common walls; report residual |
| Photo folders don't share views | outward-facing boundary shots (protocol); appearance matching |