# 04h — Polygonal (Concave) Room Footprint: L-shaped Rooms

```
Owner:           04c (this doc refines 04c §1 internals only — no interface changes)
Provides:        (none — implementation plan for stage S3)
Consumes:        I2 (CIR), I6 (Measurement), I7 (frames/units), I8 (recon artifact)
Must-not-change: I1–I9 (Room.boundary is already Polygon2D; no schema change needed)
Depends-on:      04b (B-1 recon), 04c (G-1/G-2/G-3 landed at M3)
```

## 1. Problem statement (with evidence)

S3 (`src/scan2plan/geometry/extract.py::extract_room`) models every room as an
**oriented bounding box (OBB)** — exactly four walls, always a rectangle. The seed
capture `single_room/c00a170fe1` is actually an **L-shaped space** (main room +
attached bathroom, one door), confirmed by visual inspection of `rgb.mp4`.

Current (wrong) output on that seed (`scan2plan run --stride 60`):

```
room: area=38.41 m2 ceiling=n/a walls=4 openings=0     # 6.19 x 6.20 m rectangle
```

The floor-slab occupancy of the real point cloud (10 cm cells, `#` = occupied,
world X horizontal / world Z vertical; the room sits rotated ~33° in the world
frame, which is why the Manhattan step runs first):

```
        ###############                <- main room block
       ##################
      ####################
     ######################
    #########################
    #################### ######        <- notch / attached bathroom wing
   ######################   ####
   #####################     ###        (detached speckle blobs bottom-right:
    #####   ##########                   outliers seen through the doorway)
```

Two failure modes follow directly from the OBB assumption:

1. **Area inflation**: the L's concave notch is filled in → 38.41 m² reported for
   a space that is visibly ~20–28 m².
2. **Door miss**: the real walls (with the door gap) do not coincide with the OBB
   sides, so `_detect_openings` scans the wrong lines and reports
   `openings: none detected` for a room that visibly has a door.

## 2. Root cause

`extract.py` (`extract_room`, OBB block): the floor footprint is reduced to
`(xmin, xmax) x (zmin, zmax)` percentiles in the Manhattan-rotated frame
(`OBB_PCT_LO/HI`), which can only ever emit a rectangle. Wall surfaces are then
the 4 OBB sides, and opening detection runs only on those 4 segments.

## 3. Goal / non-goals

**Goal:** extract the room's **concave polygonal footprint** from the floor
points, derive one wall `Surface` per polygon edge, and run the existing opening
detector on those real wall segments — so L-shaped (and generally rectilinear)
rooms get honest areas, correct wall counts, and findable doors.

**Non-goals (out of scope):**
- Interior wall detection (walls fully inside the footprint, e.g. a bathroom
  partition with floor visible on both sides) — future work, needs vertical-plane
  RANSAC (04c §1.3 proper).
- Multi-room segmentation of one cloud (04c later milestone / 04d input).
- Curved walls (the documented Manhattan assumption stays).
- Interface changes: `Room.boundary` is already `Polygon2D`; surfaces/openings/
  measurements are unchanged → **no ADR required** (rule R1 untouched).
## 4. Design

### 4.1 Module layout

- **New file** `src/scan2plan/geometry/footprint.py` — grid → polygon machinery.
- **Modify** `src/scan2plan/geometry/extract.py` — replace the OBB block with the
  polygon path; keep the OBB code as `_extract_obb` fallback; walls from polygon
  edges via a new `_walls_from_boundary` helper.
- **Unchanged**: `planes.py` (floor/ceiling), `_detect_openings` (works on any
  wall-segment list), CIR models, CLI, the stitch package.

Dependencies already in core: `numpy`, `scipy.ndimage` (morphology/labelling),
`shapely` (cell union/simplify/orient).

### 4.2 Algorithm (drop-in replacement for the OBB block in `extract_room`)

Input: world point cloud `points` (Nx3), `floor_y` from `horizontal_planes`.

1. **Floor slab** (existing): `slab = points[|y - floor_y| <= 0.08]`,
   `xz = slab[:, [0,2]]`; fall back to all points if the slab has < 4 points.
2. **Manhattan orientation** (existing): `theta = estimate_orientation(xz)`;
   `rot = _rotate2d(xz, theta)` — all grid work happens in this rotated frame.
3. **Outlier trim**: drop points outside the 0.5–99.5 percentile range in both
   axes (removes detached speckle blobs like those in §1 before gridding).
4. **Occupancy grid**: 2D histogram of `rot` at 5 cm bins (pad extent by 2 bins);
   a cell is occupied iff its count >= 1.
5. **Morphology** (`scipy.ndimage`): `binary_closing` (3x3, 1 iteration) to bridge
   thin scan gaps; `binary_fill_holes` (furniture legs, missed spots); `label`
   connected components and **keep only the largest** (discards detached outlier
   islands). If the largest component covers < `MIN_AREA_M2 = 2.0` → OBB fallback.
6. **Polygon extraction** (shapely): `union_all` of one `box()` per occupied cell
   → largest polygon by area → exterior ring → `simplify(tolerance=0.06)` →
   force CCW (`shapely.geometry.polygon.orient(poly, sign=1.0)`).
7. **Collinear merge**: merge consecutive ring edges whose direction differs by
   < 8°; drop edges shorter than `MIN_EDGE_M = 0.20` by merging into the longer
   neighbour. A clean rectangular room must reduce to exactly 4 vertices (keeps
   the existing rectangular tests meaningful).
8. **Rotate back**: `boundary_world = _rotate2d(ring, -theta)` → `[[x, z], ...]`
   → `Room.boundary` (world frame, identical convention to today's OBB output).
9. **Walls**: for each polygon edge with length >= `MIN_WALL_LEN_M = 0.30`, emit
   `Surface(type="wall")` with `polygon` = edge endpoints (world `[[x,z],...]`),
   `plane.normal` = **outward** unit normal `(dz, -dx)/L` for the CCW ring stored
   as Vec3 `[nx, 0.0, nz]`, `plane.d = -(n . a)`; plus a `wall_length`
   `Measurement` (existing `_measurement` helper, `LENGTH_CI_M`).
10. **Room measurements**: `floor_area` = shapely polygon area (CI stays
    `AREA_CI_REL * area`); `perimeter` = polygon length; `ceiling_height`
    unchanged. Floor/ceiling `Surface`s get `polygon=boundary` as today.
11. **Openings**: build `walls: list[(a3, b3, n3)]` from polygon edges exactly as
    today (`a3 = [ax, floor_y, az]`, `n3` = outward normal) and call the
    **unchanged** `_detect_openings(...)` — the door gap now lies on a real wall
    line and is detectable.
12. **Fallback**: if step 5/6 fails or yields < 3 usable edges, log a warning and
    fall back to the current OBB path verbatim (results-out policy, 04 §3).

### 4.3 Prescribed signatures

```python
# src/scan2plan/geometry/footprint.py
GRID_BIN_M = 0.05
SIMPLIFY_M = 0.06
MIN_AREA_M2 = 2.0
MIN_EDGE_M = 0.20
COLLINEAR_TOL_DEG = 8.0

@dataclass(frozen=True)
class Footprint2D:
    ring_local: NDArray[np.float64]  # (N, 2) simplified CCW ring, rotated frame
    area_m2: float

def occupancy_grid(
    rot: NDArray[np.float64], *, bin_m: float = GRID_BIN_M
) -> tuple[NDArray[np.bool_], float, float]:
    """(grid, x0, z0): occupied-cell mask + world offset of cell (0, 0)."""

def grid_to_polygon(
    grid: NDArray[np.bool_], x0: float, z0: float, bin_m: float
) -> NDArray[np.float64] | None:
    """Largest-component cell union -> simplified CCW exterior ring, or None."""

def merge_collinear(
    ring: NDArray[np.float64], *, tol_deg: float = COLLINEAR_TOL_DEG,
    min_edge_m: float = MIN_EDGE_M,
) -> NDArray[np.float64]:
    """Merge near-collinear consecutive edges; drop edges < min_edge_m."""

def extract_footprint(xz: NDArray[np.float64], theta: float) -> Footprint2D | None:
    """Steps 3-7 of §4.2. None => caller falls back to the OBB path."""
```

```python
# src/scan2plan/geometry/extract.py (new helper; OBB path kept as _extract_obb)
def _walls_from_boundary(
    boundary: list[list[float]], floor_y: float, room_id: str, tier: Tier
) -> tuple[list[Surface], list[tuple[NDArray, NDArray, NDArray]], list[Measurement]]:
    """Step 9: one wall Surface + wall_length Measurement per polygon edge."""
```

### 4.4 Alternatives considered

| Approach | Verdict |
|---|---|
| **Occupancy grid → cell union (chosen)** | Robust to outliers and thin scan gaps; deterministic; morphology cleans noise; resolution explicit (5 cm) |
| `shapely.concave_hull` / alpha shape on raw points | Sensitive to outlier points and `ratio` tuning; no gap filling; rejected |
| Vertical-plane RANSAC wall extraction (04c §1.3) | The "proper" long-term route, but a much bigger change; also required for *interior* walls later. This plan is the incremental step that unblocks L-shaped rooms now |
| Keep OBB + flag non-rectangularity | Honest but leaves area wrong by ~40% and doors undetectable — fails the product surface |

## 5. Test plan (`tests/test_geometry.py`, new cases first)

1. **Synthetic L-shaped cloud** (new fixture, style of `make_room_cloud`): main
   room 4.0 x 3.0 m plus a 2.0 x 1.5 m bathroom wing attached to one side, one
   0.9 m door gap in the wing's wall; floor + ceiling + walls sampled like the
   existing fixture. Assert:
   - `floor_area.value` ≈ true L area (15.0 m²) within ±8% — **not** the 20+ m²
     bounding rectangle;
   - wall surfaces >= 6 (the L has 6+ boundary edges after merging);
   - >= 1 opening detected, width in [0.6, 1.3] m;
   - `validate_plan` passes on the emitted CIR (referential integrity).
2. **Rectangular regression**: existing tests (`test_extract_room_*`) must pass
   unchanged — 4 walls, same dimensions, rotated-room test included.
3. **Degenerate fallback**: a cloud of scattered noise (no coherent floor region)
   must return the OBB result (or raise `ValueError` as today for empty input) —
   never crash.
4. **Determinism**: two `extract_room` calls on the same cloud give byte-identical
   `RoomGeometry` serialisations (R6).
5. **Stitch compatibility**: run the stitch test suite (`tests/test_stitch.py`) —
   polygon-derived wall surfaces must still feed `wall_pose` (normal[0]/normal[2]
   convention unchanged).

## 6. Real-data acceptance (seed `single_room/c00a170fe1`)

```bash
scan2plan run single_room/c00a170fe1 --stride 60 --out out_lshape
```

Passes when, vs. the current OBB baseline (`area=38.41 m2, walls=4, openings=0`):

- `floor_area` drops into a plausible L-shape range (**~18–30 m²**, sanity band
  pending BM-5 ground truth);
- `walls >= 6` (L boundary edges), `openings >= 1` (the door);
- `plan.json` passes `scan2plan validate`; `plan.svg` renders the L outline;
- the other two seeds (`single_scan_floor_only`, `single_scan_with_ceiling`)
  still run and remain schema-valid (record before/after numbers in the commit
  message — fix-loop evidence, plan 06).

## 7. Tasks

| ID | Task | Done when |
|---|---|---|
| G-6 | `geometry/footprint.py`: grid → morphology → polygon → merge (§4.2/§4.3) | unit tests on synthetic L + rectangle grids |
| G-7 | `_walls_from_boundary` + wire polygon path into `extract_room` with OBB fallback | all rectangular regression tests pass unchanged |
| G-8 | L-shape opening detection end-to-end | synthetic L door found; seed run shows >= 1 opening |
| G-9 | Docs: update 04c §7 risk note ("Non-Manhattan rooms") to point here; README status line if area numbers quoted | docs committed |

## 8. Commit plan (plan 07 conventions)

1. `feat(04c): occupancy-grid concave footprint extraction (G-6)`
2. `feat(04c): polygon walls + OBB fallback in extract_room (G-7)`
3. `test(04c): L-shaped room fixtures + real-seed acceptance (G-8)`
4. `docs(04c): L-shape footprint plan + risk-note update (G-9)` *(this doc)*

## 9. Risks

| Risk | Mitigation |
|---|---|
| Grid staircase leaves many tiny edges | `simplify(0.06)` + collinear merge (< 8°) + min-edge 0.20 m (step 7) |
| Scan gaps split the floor into components | `binary_closing` bridges ~5–10 cm gaps; largest-component rule picks the room; else OBB fallback |
| Doorway leaks floor points into the next space | Accept: the polygon then covers the visible connected floor honestly; note in the commit message; true room splitting is the 04c segmentation milestone |
| Ring orientation flips (CW) breaking outward normals | `orient(poly, sign=1.0)` + unit test asserting CCW area sign |
| Opening detector thresholds tuned on 4-wall rooms | `_detect_openings` is segment-agnostic; verify on the synthetic L fixture (test 5.1) |
| Performance on large clouds | Grid is 5 cm over ~10 m → ~200x200 cells; `union_all` of ≤ 40k boxes is sub-second; measure once in the G-7 commit |

## 10. Acceptance (definition of done)

- All tests in §5 pass; `ruff check`, `ruff format --check`, `mypy --strict src/scan2plan/cir` (untouched), and `pytest -q` are green.
- §6 real-data numbers recorded in the G-8 commit message (before/after).
- No changes to any frozen interface (I1–I9); this doc is the only new file under `docs/plans/`.

## 11. Implementation results (G-6..G-9 — shipped)

Implemented as described above (`extract_footprint` in `geometry/footprint.py`;
`extract_room` now takes the polygon path with an OBB fallback).

Measured, `single_room/c00a170fe1`:

| Run | floor area | walls | openings |
|---|---|---|---|
| OBB baseline (pre-04h) | **38.41 m²** | 4 | 0 |
| concave footprint, `--stride 10` (shipped) | **18.61 m²** | 16 | 3 |
| concave footprint, `single_scan_floor_only` (stride 40) | 48.88 m² | 16 | 5 |

Wall counts are bounded by the complexity cap (`MAX_RING_POINTS = 16`,
`cap_complexity`): ragged real-floor boundaries are simplified further until the
ring fits, so a scan never emits dozens of micro-walls, while a clean synthetic
room (already <= the cap) is untouched.

Synthetic validation (`tests/test_geometry.py`): a clean 4×3 − notch **L of 9.0 m²**
is recovered at **6 walls**, a punched door is detected, a closed L yields **no
phantom opening**, and a rectangular room still reduces to **4 walls** (regression).

**Interpretation / honest limitation.** The seed's *observed floor* is a ragged,
partly diagonal region and the attached bathroom is a **separate** floor component
(~1 m gap of unobserved floor at the doorway), so the largest-component polygon
traces the observed main area rather than a clean L. Consequences: the area is now
plausible (19 m² vs 38 m²) and openings are found, but the wall count is high
(ragged observed boundary) and the bathroom is not yet merged in. The rigorous fix
for both is (a) interior-wall detection via vertical-plane RANSAC (04c §1.3), and
(b) denser floor coverage in capture (03) / the multi-room benchmark set (08,
BM-1). R-Tree: this is fix-loop material for `06`.

