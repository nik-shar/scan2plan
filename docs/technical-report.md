# scan2plan — Technical report

**Applied AI Engineer case study · Aug 2026 · LiDAR tier.** Phone capture → stitched,
dimensioned whole-property floor plan + damage assessment, with a confidence interval on
every measurement. This report is deliberately dense; figures/tables carry the load.

> **Scope, stated up front.** The LiDAR tier runs end to end. The photos and video recon
> front-ends (plan `04b` B-2/B-3) are **not implemented**, so the three-tier gates
> (G-PSTITCH, G-TIERACC, BM-3) are **declared not delivered** rather than faked. Where a
> number depends on laser ground truth that has not been taken, it is marked
> **(unmeasured)**. Full status in `docs/compliance-matrix.md`.

## 1. Architecture

One capture → one command (`scan2plan run`) → `plan.json` (published schema) + `plan.svg`
+ `ablation.svg`. Nine single-owner interfaces (I1–I9) keep the stages decoupled; only
S1–S2 are tier-specific, S3–S9 are shared (plan `04`).

```
 I1 bundle ──► S1 ingest ──► S2 recon ──► S3 rooms ──► S4 stitch+drift
                (CIR I2)     (I8)         (04c/04h)     (04d, G-DRIFT)
                                                             │
   ┌─────────────────────────────────────────────────────────┘
   ▼
 S5 damage ──► S6 concealed ──► S7 scope ──► S8 measure+CI ──► S9 output
 (04e)         (04e)            (04e)        (04f, pending)    (04g: JSON+SVG+CLI)
```

| Stage | Module | Output (CIR) |
|---|---|---|
| S1 ingest | `ingest/` | `session`, `frames[]` |
| S2 recon | `recon/lidar.py` | `recon{points, poses, scale, quality}` |
| S3 rooms | `geometry/{walls,wall_complete,wall_graph,rooms,invariants}.py` | `rooms[]`, `surfaces[]`, `openings[]` |
| S4 stitch | `stitch/{graph,closures,optimize,se2,polygons,wire}.py` | `stitch{edges, closures, overlap_ok, ablation}` |
| S5–S7 damage | `damage/{frames,evidence,detect,rules,scope,assess}.py` | `damages[]`, `concealed[]`, `scope[]` |
| S9 output | `render/{plan_svg,svg}.py`, `cli.py` | `plan.json` (I3), `plan.svg`, `ablation.svg` |

**Failure policy (plan `04` §3):** any stage may emit a wide interval rather than fail —
the contract is "results out". Hard failures (unreadable input) exit non-zero with no
partial `plan.json`. Every stage is deterministic (fixed seeds, positional tie-breaks,
rounded output) and cached by input hash.

**No model is used.** Recon is geometric (depth + odometry), rooms/walls/stitch are
deterministic geometry, and the damage region proposer is a **disclosed colour
heuristic** (below). Nothing calls external infrastructure; no weights are fetched.

## 2. Tier design and device matrix

| Device | LiDAR sensor | LiDAR tier | Photos | Video |
|---|---|---|---|---|
| iPhone 15/16/17 (non-Pro) | ✗ | ✗ | ✅ | ✅ |
| iPhone 15/16/17 **Pro / Pro Max** | ✓ | ✅ | ✅ | ✅ |

**Rule:** the LiDAR tier needs a Pro-class device (no non-Pro iPhone has LiDAR). Route 2
(stock tools) was chosen over a custom app (ADR-0001): no signing/TestFlight friction, and
the logger export is proven against the three real seed captures rather than hypothetical.

| Tier | Front-end | Scale source | Status |
|---|---|---|---|
| **LiDAR** | depth + ARKit odometry | metric (depth, confirmed mm) | ✅ |
| Video | SfM (pycolmap/GLOMAP) | mono-depth / reference | ⬜ not implemented |
| Photos | per-room SfM (2–8 stills) | mono-depth / reference | ⬜ not implemented |

**B-0 (depth units) — the gate that had to pass before I2 froze (ADR-0002).** Back-projecting
sampled depth frames and looking for sharp horizontal planes gives a consistent camera
height across three independent captures, and only millimetres is plausible:

| Capture | camera height | room height | verdict |
|---|---|---|---|
| `c00a170fe1` | 1.401 m | — | plausible |
| `1a8384c3f6` | 1.412 m | — | plausible |
| `c7d28f72c6` | 1.464 m | 2.35 m | plausible |

Scale discrimination on `single_room`: 0.0005 → 0.71 m (no), **0.001 → 1.40 m (yes)**,
0.002 → 2.71 m (no), 0.01 → 14.4 m (no). So `depth_scale_m = 0.001` stands and the pinhole
back-projection convention is fixed.

## 3. Drift handling (G-DRIFT)

The brief fails "poses used as-is". Our policy (plan `04d` §3): **raw odometry is
initialisation only**; the stitcher always runs a correction and the ablation proves it.

Method ladder, applied in order: (a) loop-closure detection, (b) SE(2) pose-graph
optimisation, (c) plane-anchored correction (fallback). Rooms enter the graph with their
identity placement (they already share the stage-1 reconstruction frame); the optimizer
reconciles connector and loop-closure constraints with `scipy.optimize.least_squares` (trf),
weighted by inverse measurement CI.

- **Connector matching** pairs the same physical door seen from both rooms (opposing wall
  normals + width agreement widened by the openings' own CI), yielding relative constraints.
- **Loop closure** detects revisits via deterministic point-to-point ICP (2D Kabsch over a
  `cKDTree`; no RNG) and the correction magnitude is the hard drift evidence.
- **Ablation** (`run_ablation`) emits the on/off footprints from the **same code path**; the
  only difference is whether closure constraints enter the graph.

**Honest limitation:** a single capture reconstructs all rooms in one shared frame, so if no
revisit exists the ablation is `on == off` (e.g. seed `c00a170fe1`: footprint 21.65 m² both
ways, `overlap_ok = true`, no closures). This is reported, not hidden. On the multi-room
seed the stitch reports 3 rooms / 2 connectors / `overlap_ok = true` / `unstitched = false`.
`unstitched` is re-derived from **geometric adjacency** (rooms sharing a wall are connected)
because the constraint-graph criterion is wrong for a shared-frame capture.

## 4. Error budget

Every `Measurement` carries `ci_low ≤ value ≤ ci_high` (enforced in `cir/measure.py`). The
interval is a quadrature/ bootstrap combination of the terms below; widths widen with
occlusion and thin coverage, never tighten.

| Term | Typical | How it enters |
|---|---|---|
| Depth quantisation | 1 mm / unit | direct (metric scale) |
| Plane-fit RMS | ≈ 0.016 m on seeds | wall/ceiling position |
| Pose drift | ~1 % of travel (`odometry_ci_frac`) | wall endpoints |
| Grid quantisation | 2 cm (`room_grid_m`) | polygon edges, area |
| Occluded wall | ×2 (`occluded_ci_scale`) | per-wall width |
| Inferred closure | +0.05 m/m extrapolated | closure edges (wide) |
| Monte-Carlo area | 500 draws | floor-area interval |

Stage-2 completion, room closure and area all emit their parameters into the stage JSONs,
so any number can be traced to the threshold that produced it. **What is missing:** these
terms are *uncalibrated* — the widths are reasoned, not fitted to ground truth.

## 5. Calibration analysis (G-CAL) — honest status

**Not calibrated.** Intervals exist on every measurement (OUT-6 ✅) but there is no conformal
or analytic calibration fitted against laser ground truth, so **coverage is unmeasured**.
Plan `04f` specifies the intended method: bucket measurements by predicted interval width,
fit a conformal scaling per bucket (and per tier), and report empirical coverage vs nominal
(0.90). It is blocked on BM-5 (ground truth). Consequence: the intervals should be read as
*relative* confidence, not as validated 90 % coverage — stated plainly rather than implied.

## 6. The fix loop (Part 4)

The repo ships fixes with evidence (CHANGELOG + `bench/stage2_before|after/` +
`out/before_ceiling_fix/`), though not yet packaged as the required regenerable bundle. The
canonical example — **"camera cells fell in wall barriers / outside polygons"** — is the
case study's own failure mode (diagnosis without repair):

| Metric (seed) | before | after fix | root cause |
|---|---|---|---|
| stage-3 coverage | 0.73 / 0.09 / 0.26 | **1.000 / 1.000 / 1.000** | `build_regions` carved only wall+floor; walked free-space was not counted, so a room the camera crossed became a wall barrier |
| `camera_inside` | 164/215, 29/202, 59/204 | **215/215, 202/202, 204/204** | room polygons were not a superset of their region |
| rooms `c00a170fe1` | 7 (smallest 0.27 m²) | **4** | min-room rule missing → slivers emitted |
| rooms `1a8384c3f6` | 2 + 8 enclosed | **7** | walked regions dropped |
| room overlaps | 9/9 bow-ties | **0** | parallel edges not collapsed; no `resolve_overlaps` |

Two further shipped fixes: **ceiling plane selection** (a 2.01 m furniture-top and a 3.08 m
peak were reported as ceilings → now gated by cells/footprint/height + the stage-1 global
reference, else `unmeasured` with the prior), and **stage-2 evidence split** (multi-segment
wall extraction lifted `evidence_explained` 0.115→0.210, 0.051→0.149, 0.038→0.166). Every fix
moved a measured invariant, not a narrative — the six stage-3 invariants print their values
and fail loudly. **Honest gap:** the brief wants the *worst* gate chosen against ground truth;
without BM-5 we ranked by invariant violations instead.

## 7. Known failure modes

| Failure mode | Effect | Handling |
|---|---|---|
| Mirrors / glass / wet-look | depth dropouts, phantom walls | confidence gating (`confidence_min`), occluded-wall completion + ×2 CI; head-on views discouraged in the protocol |
| Low light | depth OK, damage colour unreliable | damage intervals are heuristic; low-light flagged as uncalibrated |
| Ultrawide lens / fast motion | scale/odometry drift | forbidden in the protocol (1× lens, ~0.3 m/s) |
| Thin camera coverage | region stays `unobserved_enclosed` — no dimensions | reported as an explicit state, never guessed |
| No ceiling seen | ceiling `unmeasured` with a prior (2.4–2.7 m) | never emits a false measured height |
| Single-frame capture | ablation `on == off` | reported honestly; a revisit is required for a non-degenerate ablation |
| Dark shadow on a wall | may read as `mold` (heuristic) | disclosed; the SAM/CLIP hook (plan `09`) is the intended disambiguator |

## 8. Roadmap and limitations

- **Photos/video tiers** (`04b` B-2/B-3 + B-4 scale recovery) — the only tier-specific code
  left; everything downstream is already tier-agnostic.
- **Calibration** (`04f`) — conformal coverage once ground truth exists.
- **`bench` / `report`** (`08`/`09`) + the benchmark report and fix-loop bundle — blocked on
  laser ground truth (BM-5) and, for head-to-head, a consumer-app capture.

**Limitations to be read with every number:** (1) intervals are uncalibrated; (2) no gate has
been scored against ground truth; (3) only the LiDAR tier exists, so the three-tier contract
is partially met by design and declared as such; (4) the damage detector is a heuristic with
no staged-damage benchmark. These are properties of a LiDAR-only, ground-truth-pending
submission, and they are stated rather than papered over.


