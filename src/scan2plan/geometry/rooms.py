"""Stage 3: rooms, closed polygons, per-room measurements (plan 04c/04h/04i).

Stage 3 consumes the **frozen** stage-1 evidence (`stage1_observed.json`) and the
stage-2 wall graph (`stage2_walls.json`) plus ``Config`` — never the raw cloud — and
produces a closed, dimensioned, per-room plan. It is pure geometry (no vision model),
deterministic (fixed ordering, ties broken by position, fixed RNG seed) and byte
reproducible.

Pipeline
--------
3a **closure** - greedy, cost-ordered. Each dangling wall end yields candidates
   (extend to a perpendicular wall, join a facing collinear end, snap to the observed
   floor boundary). :func:`closure_cost` scores a candidate as *length - support bonus
   + free-floor penalty*; a candidate crossing the camera path (and not an opening) is
   forbidden. Accepted pieces are tagged ``inferred_closure`` with ``assumed_length_m``.
   :func:`plan_score` sums the accepted costs (future local-search objective).
3b **rooms** - closed walls are rasterised as barriers and free space (floor +
   camera + carved) is flood-filled into regions; large regions are split at
   doorway-shaped waists (config ``waist_min_m``/``waist_max_m``) tagged
   ``inferred_opening``; camera-less enclosed regions are ``unobserved_enclosed``.
3c **per-room geometry** - an orthogonal polygon per region (edge chaining, so
   L-shapes work), wall lengths node-to-node, shoelace area, and Monte-Carlo intervals
   (fixed seed, ``mc_samples`` draws) for area and every wall length; point value is
   the best-estimate polygon; plus the observed/inferred perimeter share.
3d **ceiling** - histogram peak of in-room cells above floor + ``ceiling_min_above_floor_m``;
   with no ceiling cells the height is ``unmeasured`` with the ``prior`` interval.
3e **openings / adjacency** - width + type, host wall, the two rooms it joins.

All thresholds come from the I4 ``outline`` block (never hardcoded); the uncalibrated
ones are marked in ``docs/plans/04i-stage3.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from numpy.typing import NDArray
from scipy import ndimage
from shapely.geometry import Polygon

from scan2plan.config import Config
from scan2plan.geometry.wall_complete import WallPiece, _path_crosses

#: Provenance tags emitted by stage 3 (rule 3: nothing assumed without a tag).
OBSERVED = "observed"
INFERRED_EXTENSION = "inferred_extension"
INFERRED_OCCLUDED = "inferred_occluded"
INFERRED_CLOSURE = "inferred_closure"
INFERRED_OPENING = "inferred_opening"
PRIOR = "prior"

#: Wall provenance -> room-edge provenance.
_WALL_PROV = {
    "observed": OBSERVED,
    "inferred_extension": INFERRED_EXTENSION,
    "inferred_occluded": INFERRED_OCCLUDED,
    "inferred_dropout": INFERRED_CLOSURE,
    "inferred_closure": INFERRED_CLOSURE,
}


@dataclass(frozen=True)
class RoomParams:
    """Stage-3 thresholds, injected from the I4 ``outline`` block + seed."""

    grid_m: float
    evidence_bin_m: float
    min_step_m: float
    room_min_area_m2: float
    closure_max_m: float
    closure_wall_tol_m: float
    closure_bonus_m: float
    closure_floor_penalty: float
    waist_min_m: float
    waist_max_m: float
    mc_samples: int
    ceiling_min_above_floor_m: float
    ceiling_bin_m: float
    ceiling_prior_low_m: float
    ceiling_prior_high_m: float
    ci_base_m: float
    ci_per_m: float
    odometry_ci_frac: float
    node_merge_m: float
    seed: int
    # --- fix-loop gates (plan 04i fix loop; defaults keep older constructions valid) ---
    overlap_tol_m2: float = 0.0001
    min_room_area_m2: float = 2.0
    min_room_inradius_m: float = 0.6
    ceiling_min_cells: int = 200
    ceiling_min_footprint_frac: float = 0.20
    ceiling_height_low_m: float = 2.1
    ceiling_height_high_m: float = 4.0
    ceiling_global_tol_m: float = 0.30


def room_params_from_config(cfg: Config) -> RoomParams:
    """Build ``RoomParams`` from the I4 ``outline`` block (single source of truth)."""
    o = cfg.outline
    return RoomParams(
        grid_m=o.room_grid_m,
        evidence_bin_m=o.evidence_bin_m,
        min_step_m=o.min_step_m,
        room_min_area_m2=o.room_min_area_m2,
        closure_max_m=o.closure_max_m,
        closure_wall_tol_m=o.closure_wall_tol_m,
        closure_bonus_m=o.closure_bonus_m,
        closure_floor_penalty=o.closure_floor_penalty,
        waist_min_m=o.waist_min_m,
        waist_max_m=o.waist_max_m,
        mc_samples=o.mc_samples,
        ceiling_min_above_floor_m=o.ceiling_min_above_floor_m,
        ceiling_bin_m=o.ceiling_bin_m,
        ceiling_prior_low_m=o.ceiling_prior_low_m,
        ceiling_prior_high_m=o.ceiling_prior_high_m,
        ci_base_m=o.ci_base_m,
        ci_per_m=o.ci_per_m,
        odometry_ci_frac=o.odometry_ci_frac,
        node_merge_m=o.node_merge_m,
        seed=cfg.seed,
        overlap_tol_m2=o.overlap_tol_m2,
        min_room_area_m2=o.min_room_area_m2,
        min_room_inradius_m=o.min_room_inradius_m,
        ceiling_min_cells=o.ceiling_min_cells,
        ceiling_min_footprint_frac=o.ceiling_min_footprint_frac,
        ceiling_height_low_m=o.ceiling_height_low_m,
        ceiling_height_high_m=o.ceiling_height_high_m,
        ceiling_global_tol_m=o.ceiling_global_tol_m,
    )


# ---------------------------------------------------------------------------
# rotation helpers (same uv convention as stage 2: uv = R(theta) . xz)
# ---------------------------------------------------------------------------
def rotate_uv(xz: NDArray[np.float64], theta: float) -> NDArray[np.float64]:
    """Rotate world XZ into the Manhattan uv frame (matches stage 2)."""
    if xz.size == 0:
        return xz.reshape(0, 2)
    c, s = float(np.cos(theta)), float(np.sin(theta))
    return np.stack([xz[:, 0] * c + xz[:, 1] * s, -xz[:, 0] * s + xz[:, 1] * c], axis=1)


def uv_to_world(u: float, v: float, theta: float) -> tuple[float, float]:
    """Inverse of :func:`rotate_uv` for a single uv point -> world (x, z)."""
    c, s = float(np.cos(theta)), float(np.sin(theta))
    return (u * c - v * s, u * s + v * c)


# ---------------------------------------------------------------------------
# grid helper (uv raster)
# ---------------------------------------------------------------------------
@dataclass
class Grid:
    """A small uv raster: index [i, j] covers u in [x0+(i..i+1)*cell], v likewise."""

    x0: float
    z0: float
    cell: float
    nx: int
    nz: int

    def ij(self, u: float, v: float) -> tuple[int, int]:
        """Grid index of a uv point (floored)."""
        return int(math.floor((u - self.x0) / self.cell)), int(
            math.floor((v - self.z0) / self.cell)
        )

    def uv(self, i: float, j: float) -> tuple[float, float]:
        """uv of grid corner (i, j) (accepts fractional indices)."""
        return self.x0 + i * self.cell, self.z0 + j * self.cell

    def ij_array(
        self, u: NDArray[np.float64], v: NDArray[np.float64]
    ) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        """Vectorised :meth:`ij` for arrays of uv points."""
        return (
            np.floor((u - self.x0) / self.cell).astype(np.int64),
            np.floor((v - self.z0) / self.cell).astype(np.int64),
        )


def build_grid(pts_uv: NDArray[np.float64], cell: float, pad_m: float = 1.0) -> Grid:
    """A raster covering ``pts_uv`` plus ``pad_m`` margin on every side."""
    if pts_uv.size == 0:
        return Grid(0.0, 0.0, cell, 1, 1)
    u0, u1 = float(pts_uv[:, 0].min()) - pad_m, float(pts_uv[:, 0].max()) + pad_m
    v0, v1 = float(pts_uv[:, 1].min()) - pad_m, float(pts_uv[:, 1].max()) + pad_m
    nx = max(1, int(math.ceil((u1 - u0) / cell)) + 1)
    nz = max(1, int(math.ceil((v1 - v0) / cell)) + 1)
    return Grid(u0, v0, cell, nx, nz)


def _mark_cells(mask: NDArray[np.bool_], grid: Grid, pts_uv: NDArray[np.float64]) -> None:
    """Set mask True at every grid cell containing a point (in place)."""
    if pts_uv.size == 0:
        return
    ii = np.floor((pts_uv[:, 0] - grid.x0) / grid.cell).astype(np.int64)
    jj = np.floor((pts_uv[:, 1] - grid.z0) / grid.cell).astype(np.int64)
    ok = (ii >= 0) & (ii < grid.nx) & (jj >= 0) & (jj < grid.nz)
    mask[ii[ok], jj[ok]] = True


def _fill_bins(
    mask: NDArray[np.bool_], grid: Grid, pts_uv: NDArray[np.float64], bin_m: float
) -> None:
    """Fill the whole evidence bin (``bin_m``) around each point (in place).

    Stage-1 floor/camera cells are spaced ``bin_m`` apart; filling their full bin makes
    the flood-fill domain a solid, blocky footprint instead of disconnected specks.
    """
    if pts_uv.size == 0 or bin_m <= 0.0:
        return
    r = max(1, int(round(bin_m / grid.cell / 2)))
    ii = np.floor((pts_uv[:, 0] - grid.x0) / grid.cell).astype(np.int64)
    jj = np.floor((pts_uv[:, 1] - grid.z0) / grid.cell).astype(np.int64)
    for i, j in zip(ii, jj, strict=True):
        a0, a1 = max(0, int(i) - r), min(grid.nx, int(i) + r + 1)
        b0, b1 = max(0, int(j) - r), min(grid.nz, int(j) + r + 1)
        mask[a0:a1, b0:b1] = True


def _raster_walls(grid: Grid, walls: list[WallPiece], *, thick_cells: int = 1) -> NDArray[np.bool_]:
    """Rasterise wall pieces as axis-aligned barrier lines (optional thickness)."""
    bar = np.zeros((grid.nx, grid.nz), dtype=bool)
    for w in walls:
        if w.axis == 0:  # u = offset, spans v
            i = int(round((w.offset - grid.x0) / grid.cell))
            j0 = int(math.floor((w.start - grid.z0) / grid.cell))
            j1 = int(math.ceil((w.end - grid.z0) / grid.cell))
            for d in range(-thick_cells + 1, thick_cells):
                ii = i + d
                if 0 <= ii < grid.nx:
                    bar[ii, max(0, j0) : min(grid.nz, j1 + 1)] = True
        else:  # v = offset, spans u
            j = int(round((w.offset - grid.z0) / grid.cell))
            i0 = int(math.floor((w.start - grid.x0) / grid.cell))
            i1 = int(math.ceil((w.end - grid.x0) / grid.cell))
            for d in range(-thick_cells + 1, thick_cells):
                jj = j + d
                if 0 <= jj < grid.nz:
                    bar[max(0, i0) : min(grid.nx, i1 + 1), jj] = True
    return bar


# ---------------------------------------------------------------------------
# 3a - closure (greedy, cost-ordered)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DanglingEnd:
    """A free wall end: the piece index, which end, and its uv position."""

    piece: int
    which: int  # 0 = start, 1 = end
    axis: int
    offset: float
    coord: float
    direction: int  # -1 or +1: the outward direction along the wall line


@dataclass
class Closure:
    """An accepted closure piece (tagged ``inferred_closure``)."""

    axis: int
    offset: float
    start: float
    end: float
    kind: str  # extend_perp | join_end | snap_boundary
    cost: float
    assumed_length_m: float
    provenance: str = INFERRED_CLOSURE


def _end_is_free(walls: list[WallPiece], w: WallPiece, which: int) -> bool:
    """True when nothing continues or meets this end (within merge / perp tolerance)."""
    coord = w.start if which == 0 else w.end
    for t in walls:
        if t is w:
            continue
        if t.axis == w.axis:
            if abs(t.offset - w.offset) <= 0.15 and t.start - 0.10 <= coord <= t.end + 0.10:
                return False
        elif abs(t.offset - coord) <= 0.10 and t.start - 0.10 <= w.offset <= t.end + 0.10:
            return False
    return True


def find_dangling_ends(walls: list[WallPiece]) -> list[DanglingEnd]:
    """Every free end of the given walls (both ends), in deterministic order."""
    ends: list[DanglingEnd] = []
    for i, w in enumerate(walls):
        for which, coord, direction in ((0, w.start, -1), (1, w.end, +1)):
            if _end_is_free(walls, w, which):
                ends.append(DanglingEnd(i, which, w.axis, w.offset, coord, direction))
    ends.sort(key=lambda e: (e.axis, e.offset, e.coord, e.piece, e.which))
    return ends


def _axis_coords(cand: WallPiece, pts_uv: NDArray[np.float64], tol: float) -> NDArray[np.bool_]:
    """Boolean mask per along-candidate sample: is there a point within ``tol``?"""
    n = max(2, int(cand.length / 0.02))
    ts = np.linspace(cand.start, cand.end, n)
    if cand.axis == 0:
        perp = np.abs(pts_uv[:, 0] - cand.offset)
        along = pts_uv[:, 1]
    else:
        perp = np.abs(pts_uv[:, 1] - cand.offset)
        along = pts_uv[:, 0]
    hit = (perp <= tol)[:, None] & (np.abs(along[:, None] - ts[None, :]) <= tol)
    return hit.any(axis=0)


def closure_cost(
    cand: WallPiece,
    wall_uv: NDArray[np.float64],
    floor_uv: NDArray[np.float64],
    cam_uv: NDArray[np.float64],
    p: RoomParams,
) -> float | None:
    """Cost of a closure candidate (lower is better), or ``None`` if forbidden.

    cost = length - ``closure_bonus_m`` * (supported length)
                 + ``closure_floor_penalty`` * (length crossing free floor)

    Forbidden when longer than ``closure_max_m`` or crossing the camera path (rule 6:
    never close across the camera unless the gap is a classified opening).
    """
    length = cand.length
    if length <= 0.0 or length > p.closure_max_m:
        return None
    if cam_uv.shape[0] >= 2 and _path_crosses(cam_uv, cand.axis, cand.offset, cand.start, cand.end):
        return None
    support = (
        float(_axis_coords(cand, wall_uv, p.closure_wall_tol_m).mean()) if wall_uv.size else 0.0
    )
    floor = (
        float(_axis_coords(cand, floor_uv, p.closure_wall_tol_m).mean()) if floor_uv.size else 0.0
    )
    return float(
        length - p.closure_bonus_m * length * support + p.closure_floor_penalty * length * floor
    )


def _closure_candidates(
    d: DanglingEnd, walls: list[WallPiece], floor_uv: NDArray[np.float64], p: RoomParams
) -> list[tuple[str, WallPiece]]:
    """Candidates for one dangling end: extend_perp, join_end, snap_boundary."""
    out: list[tuple[str, WallPiece]] = []
    coord, sign = d.coord, d.direction

    def reached(target: float) -> bool:
        return 0.03 < (target - coord) * sign <= p.closure_max_m

    # (1) extend along the wall line to the nearest perpendicular wall.
    for t in walls:
        if t.axis != d.axis and t.start - 0.10 <= d.offset <= t.end + 0.10 and reached(t.offset):
            g0, g1 = sorted((coord, t.offset))
            out.append(("extend_perp", WallPiece(d.axis, d.offset, g0, g1)))

    # (2) join a facing collinear dangling end.
    own = walls[d.piece]
    for j, t in enumerate(walls):
        if j == d.piece or t.axis != d.axis or abs(t.offset - d.offset) > 0.15:
            continue
        for tc, tdir in ((t.start, -1), (t.end, +1)):
            if tdir * sign == -1 and reached(tc):
                g0, g1 = sorted((coord, tc))
                out.append(("join_end", WallPiece(d.axis, 0.5 * (own.offset + t.offset), g0, g1)))

    # (3) snap outward to the observed floor boundary (extent along the wall line).
    if floor_uv.size:
        band = (
            np.abs(floor_uv[:, 0] - d.offset) <= 0.5
            if d.axis == 0
            else np.abs(floor_uv[:, 1] - d.offset) <= 0.5
        )
        along = floor_uv[band, 1] if d.axis == 0 else floor_uv[band, 0]
        if along.size:
            target = float(along.max()) if sign > 0 else float(along.min())
            if reached(target):
                g0, g1 = sorted((coord, target))
                out.append(("snap_boundary", WallPiece(d.axis, d.offset, g0, g1)))
    return out


def _regions_enclosed(walls: list[WallPiece], cam_uv: NDArray[np.float64], grid: Grid) -> bool:
    """True when no camera cell leaks to the raster border through gaps."""
    if cam_uv.shape[0] == 0:
        return True
    free = ~_raster_walls(grid, walls)
    lab, _n = ndimage.label(free, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
    border = set(lab[0, :].tolist()) | set(lab[-1, :].tolist())
    border |= set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    border.discard(0)
    ci, cj = grid.ij_array(cam_uv[:, 0], cam_uv[:, 1])
    ok = (ci >= 0) & (ci < grid.nx) & (cj >= 0) & (cj < grid.nz)
    cam_labels = set(lab[ci[ok], cj[ok]].tolist())
    cam_labels.discard(0)
    return cam_labels.isdisjoint(border)


def _copy_piece(w: WallPiece) -> WallPiece:
    """A shallow copy of a wall piece (so closure never mutates stage-2 objects)."""
    return WallPiece(
        axis=w.axis,
        offset=w.offset,
        start=w.start,
        end=w.end,
        provenance=w.provenance,
        rule=w.rule,
        ci_m=w.ci_m,
        extension=w.extension,
        kind=w.kind,
        support=w.support,
        coverage=w.coverage,
        thickness=w.thickness,
        merged_from=w.merged_from,
        peak_strength=w.peak_strength,
    )


def close_walls(
    walls: list[WallPiece],
    wall_uv: NDArray[np.float64],
    floor_uv: NDArray[np.float64],
    cam_uv: NDArray[np.float64],
    grid: Grid,
    p: RoomParams,
) -> tuple[list[WallPiece], list[Closure], float]:
    """Greedy, cost-ordered closure. Returns (closed walls, closures, plan_score).

    After each accept the dangling ends and candidates are regenerated (re-evaluation),
    so an accepted closure consumes ends and a candidate is never duplicated. Stops when
    every camera region is enclosed or no valid candidate remains (rule 6: camera-crossing
    candidates are forbidden).
    """
    closed = [_copy_piece(w) for w in walls]
    closures: list[Closure] = []
    for _ in range(500):
        if _regions_enclosed(closed, cam_uv, grid):
            break
        cands: list[tuple[float, str, WallPiece]] = []
        for d in find_dangling_ends(closed):
            for kind, piece in _closure_candidates(d, closed, floor_uv, p):
                cost = closure_cost(piece, wall_uv, floor_uv, cam_uv, p)
                if cost is not None:
                    cands.append((cost, kind, piece))
        if not cands:
            break
        cands.sort(
            key=lambda c: (
                round(c[0], 6),
                c[2].axis,
                round(c[2].offset, 4),
                round(c[2].start, 4),
                round(c[2].end, 4),
            )
        )
        cost, kind, piece = cands[0]
        piece.provenance = INFERRED_CLOSURE
        piece.rule = kind
        piece.ci_m = p.ci_base_m + p.ci_per_m * piece.length
        piece.extension = piece.length
        closed.append(piece)
        closures.append(
            Closure(
                piece.axis,
                piece.offset,
                piece.start,
                piece.end,
                kind,
                round(cost, 4),
                round(piece.length, 4),
            )
        )
    return closed, closures, plan_score(closures)


def plan_score(closures: list[Closure]) -> float:
    """Sum of accepted closure costs (the future local-search objective; not searched)."""
    return round(float(sum(c.cost for c in closures)), 4)


# ---------------------------------------------------------------------------
# 3b - regions (flood fill) + doorway-shaped waist splits
# ---------------------------------------------------------------------------
@dataclass
class Region:
    """A flood-filled free-space region (candidate room)."""

    id: str
    cells: set[tuple[int, int]]  # grid indices [i, j]
    has_camera: bool
    status: str  # room | unobserved_enclosed | discarded


@dataclass
class WaistSplit:
    """A doorway-shaped narrowing that splits a region (tagged ``inferred_opening``)."""

    axis: int
    offset: float
    start: float
    end: float
    width_m: float
    provenance: str = INFERRED_OPENING


def build_regions(
    closed: list[WallPiece],
    grid: Grid,
    domain: NDArray[np.bool_],
    cam_uv: NDArray[np.float64],
    p: RoomParams,
) -> list[Region]:
    """Flood-fill the free space inside ``domain`` bounded by ``closed`` walls."""
    barrier = _raster_walls(grid, closed)
    free = domain & ~barrier
    labels, n = ndimage.label(free, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
    cam_cells: set[tuple[int, int]] = set()
    if cam_uv.size:
        ci, cj = grid.ij_array(cam_uv[:, 0], cam_uv[:, 1])
        ok = (ci >= 0) & (ci < grid.nx) & (cj >= 0) & (cj < grid.nz)
        cam_cells = {(int(a), int(b)) for a, b in zip(ci[ok], cj[ok], strict=True)}
    regions: list[Region] = []
    cell_area = grid.cell * grid.cell
    for lab in range(1, n + 1):
        ii, jj = np.where(labels == lab)
        cells = {(int(a), int(b)) for a, b in zip(ii, jj, strict=True)}
        if not cells:
            continue
        area = len(cells) * cell_area
        has_cam = bool(cells & cam_cells)
        if area < p.room_min_area_m2:
            status = "discarded"
        else:
            status = "room" if has_cam else "unobserved_enclosed"
        regions.append(Region(id="", cells=cells, has_camera=has_cam, status=status))
    regions.sort(key=lambda r: (-len(r.cells), min(r.cells)))
    return regions


def _span_width(cells: set[tuple[int, int]], k: int, index: int) -> int:
    """Number of region cells at a given grid index along ``k`` (0 = u, 1 = v)."""
    return sum(1 for c in cells if c[k] == index)


def find_waists(region: Region, grid: Grid, p: RoomParams) -> list[WaistSplit]:
    """Doorway-shaped narrowings (width in [waist_min, waist_max], a local minimum)."""
    cells = region.cells
    out: list[WaistSplit] = []
    window = max(5, int(round(0.30 / grid.cell)))
    for axis in (0, 1):
        k = axis
        idxs = sorted({c[k] for c in cells})
        span = {i: _span_width(cells, k, i) for i in range(idxs[0], idxs[-1] + 1)}
        for i in range(idxs[0] + 1, idxs[-1]):
            left, right, here = span.get(i - 1, 0), span.get(i + 1, 0), span.get(i, 0)
            if not (left and right and here and here < left and here < right):
                continue
            width = here * grid.cell
            if not (p.waist_min_m <= width <= p.waist_max_m):
                continue
            lo, hi = i - window, i + window
            neigh = [span.get(x, 0) for x in range(lo, hi + 1)]
            if here > min(neigh) or max(neigh) * grid.cell < p.waist_max_m:
                continue  # not a strong, isolated pinch that opens to a real room
            coords = sorted(c[1 - k] for c in cells if c[k] == i)
            along0 = grid.uv(i, coords[0])[1 - k] if axis == 0 else grid.uv(coords[0], i)[0]
            along1 = grid.uv(i, coords[-1])[1 - k] if axis == 0 else grid.uv(coords[-1], i)[0]
            off = grid.uv(i, 0)[0] if axis == 0 else grid.uv(0, i)[1]
            out.append(WaistSplit(axis, off, along0, along1, width))
    out.sort(key=lambda w: (round(w.width_m, 4), w.axis, round(w.offset, 4)))
    return out


def split_regions(
    regions: list[Region], grid: Grid, cam_cells: set[tuple[int, int]], p: RoomParams
) -> tuple[list[Region], list[WaistSplit]]:
    """Split regions at their narrowest doorway-shaped waist, repeatedly (deterministic)."""
    splits: list[WaistSplit] = []
    work = list(regions)
    out: list[Region] = []
    guard = 0
    while work and guard < 200:
        guard += 1
        reg = work.pop(0)
        waists = find_waists(reg, grid, p) if reg.status == "room" else []
        if not waists:
            out.append(reg)
            continue
        w = waists[0]
        k = 0 if w.axis == 0 else 1
        origin = grid.x0 if k == 0 else grid.z0
        cut = int(round((w.offset - origin) / grid.cell))
        left = {c for c in reg.cells if c[k] < cut}
        right = {c for c in reg.cells if c[k] >= cut}
        min_cells = max(p.room_min_area_m2 / (grid.cell * grid.cell), 0.15 * len(reg.cells))
        if len(left) < min_cells or len(right) < min_cells:
            out.append(reg)
            continue
        splits.append(w)
        # A waist is a doorway (passable), not a wall: both halves inherit "visited".
        for side in (left, right):
            work.append(Region(id="", cells=side, has_camera=reg.has_camera, status=reg.status))
    out.sort(key=lambda r: (-len(r.cells), min(r.cells)))
    return out, splits


# ---------------------------------------------------------------------------
# 3c - per-room polygon, wall lengths, area, Monte-Carlo intervals
# ---------------------------------------------------------------------------
@dataclass
class RoomEdge:
    """One orthogonal edge of a room polygon, with its wall + provenance."""

    axis: int  # 0 = u = offset (spans v); 1 = v = offset (spans u)
    offset: float
    start: float
    end: float
    wall: int | None
    provenance: str
    ci_m: float


@dataclass
class Room:
    """A closed room: polygon (uv), area, wall lengths, perimeter provenance share."""

    id: str
    status: str
    indices: list[str]
    polygon_uv: list[tuple[float, float]]
    edges: list[RoomEdge]
    area_m2: float
    area_ci: tuple[float, float]
    perimeter_observed_m: float
    perimeter_total_m: float
    wall_lengths: list[dict[str, object]]
    cells: int
    ceiling: dict[str, object] = field(default_factory=dict)
    region_cells: set[tuple[int, int]] = field(default_factory=set)


def _merge_loop(loop: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop collinear/spike vertices of a float rectilinear loop (keeps it simple)."""
    if len(loop) > 1 and loop[0] == loop[-1]:
        loop = loop[:-1]
    out: list[tuple[float, float]] = []
    n = len(loop)
    for k in range(n):
        prev, cur, nxt = loop[k - 1], loop[k], loop[(k + 1) % n]
        cross = (cur[0] - prev[0]) * (nxt[1] - cur[1]) - (cur[1] - prev[1]) * (nxt[0] - cur[0])
        if abs(cross) > 1e-9:
            out.append(cur)
    return out or loop


def _collapse_parallel(edges: list[RoomEdge]) -> list[RoomEdge]:
    """Merge runs of consecutive same-axis edges into one (keeps the widest span).

    Snapping can move two parallel edges of a staircase boundary onto the same
    offset, leaving the edge between them degenerate; ``_corners_from_offsets`` then
    falls back to a corner that self-intersects the loop (a bow-tie). Collapsing the
    run first keeps every corner the intersection of a perpendicular pair.
    """
    if not edges:
        return edges
    out: list[RoomEdge] = []

    def _merge(a: RoomEdge, b: RoomEdge) -> RoomEdge:
        return RoomEdge(
            a.axis,
            a.offset,
            min(a.start, b.start),
            max(a.end, b.end),
            a.wall if a.wall is not None else b.wall,
            a.provenance,
            max(a.ci_m, b.ci_m),
        )

    for e in edges:
        if out and out[-1].axis == e.axis:
            out[-1] = _merge(out[-1], e)
        else:
            out.append(e)
    if len(out) > 1 and out[0].axis == out[-1].axis:
        out[0] = _merge(out[0], out.pop())
    return out


def _ring_to_corners(poly: Polygon) -> list[tuple[float, float]]:
    """Exterior ring of an axis-aligned polygon -> rectilinear corners (no collinear)."""
    if poly.is_empty:
        return []
    geom = poly if poly.geom_type == "Polygon" else max(poly.geoms, key=lambda g: g.area)
    pts = [(round(float(x), 6), round(float(y), 6)) for x, y in geom.exterior.coords[:-1]]
    return _merge_loop(pts)


def _directed_boundary(cells: set[tuple[int, int]]) -> dict[tuple[int, int], list[tuple[int, int]]]:
    """Directed unit edges around the region, interior on the left (CCW loops)."""
    out: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for i, j in cells:
        if (i, j - 1) not in cells:  # bottom -> +i
            out.setdefault((i, j), []).append((i + 1, j))
        if (i + 1, j) not in cells:  # right -> +j
            out.setdefault((i + 1, j), []).append((i + 1, j + 1))
        if (i, j + 1) not in cells:  # top -> -i
            out.setdefault((i + 1, j + 1), []).append((i, j + 1))
        if (i - 1, j) not in cells:  # left -> -j
            out.setdefault((i, j + 1), []).append((i, j))
    return out


def _turn_rank(prev: tuple[int, int], cur: tuple[int, int], nxt: tuple[int, int]) -> int:
    """Rank a turn: straight=0, then left/right, so chaining prefers straight."""
    din = (cur[0] - prev[0], cur[1] - prev[1])
    dout = (nxt[0] - cur[0], nxt[1] - cur[1])
    if dout == din:
        return 0
    return 1  # any turn keeps the loop simple for 4-connected regions


def _trace_loop(
    edges: dict[tuple[int, int], list[tuple[int, int]]], start: tuple[int, int]
) -> list[tuple[int, int]]:
    """Follow directed edges from ``start`` into one closed loop of corner points."""
    path = [start]
    prev = None
    cur = start
    for _ in range(200000):
        outs = edges.get(cur, [])
        if not outs:
            break
        if prev is None:
            nxt = min(outs)
        elif len(outs) == 1:
            nxt = outs[0]
        else:
            nxt = min(outs, key=lambda o: (_turn_rank(prev, cur, o), o))
        path.append(nxt)
        prev, cur = cur, nxt
        if cur == start:
            break
    return path


def _merge_collinear(loop: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Drop corners that lie mid-way along a straight run."""
    if len(loop) > 1 and loop[0] == loop[-1]:
        loop = loop[:-1]
    out: list[tuple[int, int]] = []
    n = len(loop)
    for k in range(n):
        prev, cur, nxt = loop[k - 1], loop[k], loop[(k + 1) % n]
        if (cur[0] - prev[0], cur[1] - prev[1]) != (nxt[0] - cur[0], nxt[1] - cur[1]):
            out.append(cur)
    return out or loop


def region_polygon(cells: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """The outer boundary corners (grid indices) of a 4-connected region."""
    edges = _directed_boundary(cells)
    if not edges:
        return []
    start = min(edges)
    loop = _trace_loop(edges, start)
    return _merge_collinear(loop)


def _match_wall(
    axis: int, offset: float, start: float, end: float, walls: list[WallPiece]
) -> int | None:
    """Nearest wall piece on the same line covering the span (for a room edge)."""
    best: tuple[float, int] | None = None
    for k, w in enumerate(walls):
        if w.axis != axis or abs(w.offset - offset) > 0.12:
            continue
        if min(end, w.end) - max(start, w.start) < -0.05:
            continue
        d = abs(w.offset - offset)
        if best is None or d < best[0]:
            best = (d, k)
    return best[1] if best else None


def _provenance_of(wall: WallPiece | None) -> str:
    """Room-edge provenance from the matched wall (rule 3)."""
    if wall is None:
        return PRIOR
    return _WALL_PROV.get(wall.provenance, INFERRED_CLOSURE)


def room_edges(
    corners: list[tuple[int, int]], grid: Grid, walls: list[WallPiece]
) -> list[RoomEdge]:
    """Turn polygon corners (grid indices) into oriented orthogonal edges + provenance."""
    edges: list[RoomEdge] = []
    n = len(corners)
    for k in range(n):
        a, b = corners[k], corners[(k + 1) % n]
        if a[0] == b[0]:  # constant u -> vertical: u = offset, spans v
            axis = 0
            offset = grid.uv(a[0], 0)[0]
            start, end = sorted((grid.uv(0, a[1])[1], grid.uv(0, b[1])[1]))
        elif a[1] == b[1]:  # constant v -> horizontal: v = offset, spans u
            axis = 1
            offset = grid.uv(0, a[1])[1]
            start, end = sorted((grid.uv(a[0], 0)[0], grid.uv(b[0], 0)[0]))
        else:  # not orthogonal (should not happen on the grid)
            continue
        if end - start < 1e-6:
            continue
        widx = _match_wall(axis, offset, start, end, walls)
        wall = walls[widx] if widx is not None else None
        edges.append(
            RoomEdge(
                axis=axis,
                offset=offset,
                start=start,
                end=end,
                wall=widx,
                provenance=_provenance_of(wall),
                ci_m=(wall.ci_m if wall is not None else 0.03),
            )
        )
    return edges


def snap_offsets(
    edges: list[RoomEdge], walls: list[WallPiece], merge_tol_m: float, min_step_m: float
) -> list[RoomEdge]:
    """Snap each edge's offset to a matched wall, else to the ``min_step_m`` grid.

    Snapping floor-derived edges onto the ``min_step_m`` grid collapses the near-equal
    staircase steps of a ragged region boundary, so the polygon has few corners while
    every wall edge keeps its exact observed/inferred position.
    """
    out: list[RoomEdge] = []
    for e in edges:
        near = [w for w in walls if w.axis == e.axis and abs(w.offset - e.offset) <= merge_tol_m]
        if near:
            off = min(near, key=lambda w: abs(w.offset - e.offset)).offset
        else:
            off = round(e.offset / min_step_m) * min_step_m
        out.append(RoomEdge(e.axis, off, e.start, e.end, e.wall, e.provenance, e.ci_m))
    return out


def simplify_polygon(
    corners: list[tuple[int, int]],
    grid: Grid,
    walls: list[WallPiece],
    merge_tol_m: float,
    min_step_m: float,
) -> tuple[list[RoomEdge], list[tuple[float, float]]]:
    """Region boundary -> snapped, de-duplicated rectilinear edges + corners.

    Each pass snaps offsets (walls exact; floor edges to the ``min_step_m`` grid) and
    rebuilds corners, collapsing the staircase steps of a ragged region boundary.
    """
    uv = [grid.uv(i, j) for i, j in corners]
    edges = _edges_from_uv(uv, walls)
    for _ in range(4):
        edges = _collapse_parallel(snap_offsets(edges, walls, merge_tol_m, min_step_m))
        uv2 = _dedupe_loop(_corners_from_offsets(edges, [e.offset for e in edges]))
        if len(uv2) < 4 or len(uv2) == len(uv):
            final = _edges_from_uv(uv2, walls)
            if Polygon(uv2).is_valid or len(uv2) < 4:
                return final, uv2
            return _edges_from_uv(uv, walls), uv  # bow-tie: keep the valid raw boundary
        uv = uv2
        edges = _edges_from_uv(uv, walls)
    if not Polygon(uv).is_valid:
        raw = [grid.uv(i, j) for i, j in corners]
        return _edges_from_uv(raw, walls), raw
    return edges, uv


def _dedupe_loop(corners: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop coincident consecutive corners and a repeated closing corner."""
    out: list[tuple[float, float]] = []
    for c in corners:
        if not out or abs(c[0] - out[-1][0]) > 1e-9 or abs(c[1] - out[-1][1]) > 1e-9:
            out.append(c)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return out


def _edges_from_uv(corners: list[tuple[float, float]], walls: list[WallPiece]) -> list[RoomEdge]:
    """Build orthogonal edges from a rectilinear uv corner loop, matching walls."""
    out: list[RoomEdge] = []
    n = len(corners)
    for k in range(n):
        a, b = corners[k], corners[(k + 1) % n]
        if abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9:
            continue
        if abs(a[0] - b[0]) < 1e-9:
            axis, offset = 0, a[0]
            start, end = sorted((a[1], b[1]))
        else:
            axis, offset = 1, a[1]
            start, end = sorted((a[0], b[0]))
        widx = _match_wall(axis, offset, start, end, walls)
        wall = walls[widx] if widx is not None else None
        out.append(
            RoomEdge(
                axis,
                offset,
                start,
                end,
                widx,
                _provenance_of(wall),
                wall.ci_m if wall is not None else 0.03,
            )
        )
    return out


def _corners_from_offsets(edges: list[RoomEdge], offsets: list[float]) -> list[tuple[float, float]]:
    """Corner list from consecutive edge lines (orthogonal intersection)."""
    n = len(edges)
    corners: list[tuple[float, float]] = []
    for k in range(n):
        e0, e1 = edges[k], edges[(k + 1) % n]
        o0, o1 = offsets[k], offsets[(k + 1) % n]
        if e0.axis == 0 and e1.axis == 1:
            corners.append((o0, o1))
        elif e0.axis == 1 and e1.axis == 0:
            corners.append((o1, o0))
        else:  # parallel consecutive edges: fall back to the stored corner run
            corners.append((o0, o1))
    return corners


def polygon_area(corners: list[tuple[float, float]]) -> float:
    """Shoelace area (m2) of a uv polygon."""
    n = len(corners)
    if n < 3:
        return 0.0
    s = 0.0
    for k in range(n):
        u0, v0 = corners[k]
        u1, v1 = corners[(k + 1) % n]
        s += u0 * v1 - u1 * v0
    return abs(s) / 2.0


def _edge_len(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(math.hypot(a[0] - b[0], a[1] - b[1]))


def _edge_half_width(e: RoomEdge, p: RoomParams) -> float:
    """Interval half-width for a room edge (spec 3c).

    observed -> bootstrap + odometry term (``odometry_ci_frac`` of the length);
    inferred -> ``ci_base_m + ci_per_m * assumed_length`` (assumed = the edge length).
    """
    length = e.end - e.start
    if e.provenance == OBSERVED:
        return max(e.ci_m, p.odometry_ci_frac * length)
    return p.ci_base_m + p.ci_per_m * length


def monte_carlo_room(
    edges: list[RoomEdge], p: RoomParams
) -> tuple[tuple[float, float], list[tuple[float, float]]]:
    """Monte-Carlo (area CI, per-edge length CIs) from sampled wall positions.

    Each matched wall draws its offset from a normal with half-width = the wall's own
    interval (observed: bootstrap + 1% of length; inferred: ``ci_base + ci_per_m * L``).
    Fixed seed, ``mc_samples`` draws; reports the 2.5/97.5 percentiles.
    """
    n = len(edges)
    if n < 3 or p.mc_samples <= 0:
        return (0.0, 0.0), [(0.0, 0.0)] * n
    # group edges that share a wall (all other edges use their own index).
    group_of: list[object] = []
    seen: dict[object, int] = {}
    for k, e in enumerate(edges):
        key: object = ("wall", e.wall) if e.wall is not None else ("edge", k)
        group_of.append(key)
        seen.setdefault(key, k)
    base_offsets = [e.offset for e in edges]
    rng = np.random.default_rng(p.seed % (2**32))
    area_draws = np.empty(p.mc_samples)
    len_draws = np.empty((p.mc_samples, n))
    for draw in range(p.mc_samples):
        override = list(base_offsets)
        for _key, first in seen.items():
            e = edges[first]
            half = _edge_half_width(e, p)
            override[first] = float(rng.normal(e.offset, max(half, 1e-4) / 1.96))
        for k, gkey in enumerate(group_of):
            override[k] = override[seen[gkey]]
        corners = _corners_from_offsets(edges, override)
        area_draws[draw] = polygon_area(corners)
        for k in range(n):
            len_draws[draw, k] = _edge_len(corners[k], corners[(k + 1) % n])
    area_ci = (
        float(np.percentile(area_draws, 2.5)),
        float(np.percentile(area_draws, 97.5)),
    )
    len_ci = [
        (float(np.percentile(len_draws[:, k], 2.5)), float(np.percentile(len_draws[:, k], 97.5)))
        for k in range(n)
    ]
    return area_ci, len_ci


def wall_lengths(
    edges: list[RoomEdge],
    len_ci: list[tuple[float, float]],
    nodes_uv: NDArray[np.float64],
    p: RoomParams,
) -> list[dict[str, object]]:
    """Node-to-node wall lengths along a room edge (splitting at projection nodes)."""
    out: list[dict[str, object]] = []
    for k, e in enumerate(edges):
        cuts = [e.start, e.end]
        if nodes_uv.size:
            perp = nodes_uv[:, 0] if e.axis == 0 else nodes_uv[:, 1]
            along = nodes_uv[:, 1] if e.axis == 0 else nodes_uv[:, 0]
            for a in along[np.abs(perp - e.offset) <= p.node_merge_m]:
                if e.start + 1e-6 < a < e.end - 1e-6:
                    cuts.append(float(a))
        cuts = sorted(cuts)
        total = e.end - e.start
        ci_here = len_ci[k] if k < len(len_ci) else (0.0, 0.0)
        for a, b in zip(cuts, cuts[1:], strict=False):
            frag = b - a
            half = (ci_here[1] - ci_here[0]) / 2.0 * (frag / total if total else 0.0)
            out.append(
                {
                    "axis": "u" if e.axis == 0 else "v",
                    "offset_m": round(e.offset, 4),
                    "start_m": round(a, 4),
                    "end_m": round(b, 4),
                    "length_m": round(frag, 4),
                    "ci_low_m": round(frag - abs(half), 4),
                    "ci_high_m": round(frag + abs(half), 4),
                    "provenance": e.provenance,
                }
            )
    out.sort(key=lambda d: (str(d["axis"]), float(d["offset_m"]), float(d["start_m"])))
    return out


# ---------------------------------------------------------------------------
# 3d - ceiling height (per room)
# ---------------------------------------------------------------------------
def point_in_polygon(u: float, v: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon (uv)."""
    inside = False
    n = len(poly)
    for k in range(n):
        u0, v0 = poly[k]
        u1, v1 = poly[(k + 1) % n]
        if (v0 > v) != (v1 > v):
            u_cross = u0 + (v - v0) * (u1 - u0) / (v1 - v0) if v1 != v0 else u0
            if u < u_cross:
                inside = not inside
    return inside


def _ceiling_prior(p: RoomParams) -> dict[str, object]:
    """The ``unmeasured`` ceiling record: a prior interval, never null (spec 3d)."""
    value = round(0.5 * (p.ceiling_prior_low_m + p.ceiling_prior_high_m), 4)
    return {
        "status": "unmeasured",
        "value": value,
        "ci_low": p.ceiling_prior_low_m,
        "ci_high": p.ceiling_prior_high_m,
        "method": "prior",
        "provenance": PRIOR,
        "support": 0.0,
    }


def room_ceiling(
    polygon_uv: list[tuple[float, float]],
    points_xyz: NDArray[np.float64] | None,
    theta: float,
    floor_y: float,
    p: RoomParams,
) -> dict[str, object]:
    """Ceiling height for a room, or an ``unmeasured`` prior when no ceiling cells exist."""
    if points_xyz is None or points_xyz.size == 0 or len(polygon_uv) < 3:
        return _ceiling_prior(p)
    uv = rotate_uv(points_xyz[:, [0, 2]], theta)
    u0, u1 = min(c[0] for c in polygon_uv), max(c[0] for c in polygon_uv)
    v0, v1 = min(c[1] for c in polygon_uv), max(c[1] for c in polygon_uv)
    inside_bbox = (uv[:, 0] >= u0) & (uv[:, 0] <= u1) & (uv[:, 1] >= v0) & (uv[:, 1] <= v1)
    ys = [
        float(points_xyz[idx, 1])
        for idx in np.flatnonzero(inside_bbox)
        if float(points_xyz[idx, 1]) > floor_y + p.ceiling_min_above_floor_m
        and point_in_polygon(float(uv[idx, 0]), float(uv[idx, 1]), polygon_uv)
    ]
    if not ys:
        return _ceiling_prior(p)
    arr = np.array(ys, dtype=np.float64)
    edges = np.arange(float(arr.min()), float(arr.max()) + p.ceiling_bin_m, p.ceiling_bin_m)
    if len(edges) < 2:
        return _ceiling_prior(p)
    hist, edges = np.histogram(arr, bins=edges)
    peak = int(np.argmax(hist))
    centre = float((edges[peak] + edges[peak + 1]) / 2.0)
    near = arr[np.abs(arr - centre) <= 0.05]
    if near.size < max(50, 0.10 * arr.size):
        return _ceiling_prior(p)  # no concentrated plane: report a prior, not a number
    rms = float(np.std(near)) if near.size else 0.0
    height = centre - floor_y
    half = max(p.ci_base_m, 2.0 * rms)
    return {
        "status": "measured",
        "value": round(height, 4),
        "ci_low": round(max(0.0, height - half), 4),
        "ci_high": round(height + half, 4),
        "method": "plane_fit",
        "provenance": OBSERVED,
        "support": round(float(near.size) / float(arr.size), 4) if arr.size else 0.0,
    }


# ---------------------------------------------------------------------------
# 3e - openings and adjacency
# ---------------------------------------------------------------------------
@dataclass
class StageOpening:
    """An opening between rooms (camera-crossed gap or a doorway-shaped waist)."""

    id: str
    axis: int
    offset: float
    start: float
    end: float
    kind: str  # door | window | passage
    provenance: str
    rooms: tuple[str, str] | None
    width_m: float


def _room_at(u: float, v: float, rooms: list[Room]) -> str | None:
    """The room id whose polygon contains a uv point."""
    for room in rooms:
        if point_in_polygon(u, v, room.polygon_uv):
            return room.id
    return None


def build_openings(
    stage2_openings: list[dict[str, object]],
    waists: list[WaistSplit],
    rooms: list[Room],
) -> list[StageOpening]:
    """Openings from stage-2 camera-crossed gaps + room-split waists, with room pairs."""
    out: list[StageOpening] = []
    idx = 0
    for o in stage2_openings:
        axis = 0 if o.get("axis") == "u" else 1
        offset = float(o["offset_m"])
        start, end = float(o["start_m"]), float(o["end_m"])
        mid = 0.5 * (start + end)
        a = (offset - 0.05, mid) if axis == 0 else (mid, offset - 0.05)
        b = (offset + 0.05, mid) if axis == 0 else (mid, offset + 0.05)
        ra, rb = _room_at(*a, rooms), _room_at(*b, rooms)
        idx += 1
        out.append(
            StageOpening(
                id=f"open_{idx}",
                axis=axis,
                offset=offset,
                start=start,
                end=end,
                kind="door",
                provenance=OBSERVED,
                rooms=(ra, rb) if ra and rb and ra != rb else None,
                width_m=end - start,
            )
        )
    for w in waists:
        mid = 0.5 * (w.start + w.end)
        a = (w.offset - 0.05, mid) if w.axis == 0 else (mid, w.offset - 0.05)
        b = (w.offset + 0.05, mid) if w.axis == 0 else (mid, w.offset + 0.05)
        ra, rb = _room_at(*a, rooms), _room_at(*b, rooms)
        idx += 1
        out.append(
            StageOpening(
                id=f"open_{idx}",
                axis=w.axis,
                offset=w.offset,
                start=w.start,
                end=w.end,
                kind="door",
                provenance=INFERRED_OPENING,
                rooms=(ra, rb) if ra and rb and ra != rb else None,
                width_m=w.width_m,
            )
        )
    out.sort(key=lambda o: (o.axis, round(o.offset, 4), round(o.start, 4)))
    return out


def adjacency(openings: list[StageOpening]) -> list[dict[str, object]]:
    """Room adjacency derived from openings (each pair once, sorted ids)."""
    pairs: dict[tuple[str, str], str] = {}
    for o in openings:
        if o.rooms:
            key: tuple[str, str] = tuple(sorted(o.rooms))  # type: ignore[assignment]
            pairs.setdefault(key, o.id)
    return [
        {"rooms": [a, b], "via": oid, "provenance": INFERRED_OPENING}
        for (a, b), oid in sorted(pairs.items())
    ]


# ---------------------------------------------------------------------------
# 3f - orchestration: stage1 + stage2 + config -> rooms / openings / adjacency
# ---------------------------------------------------------------------------
def _walls_from_stage2(stage2: dict[str, object]) -> list[WallPiece]:
    """Rebuild stage-2 ``Segment`` objects as ``WallPiece``s (uv frame already set)."""
    from scan2plan.geometry.walls import _segment_to_piece, segments_from_payload

    return [_segment_to_piece(s) for s in segments_from_payload(stage2)]


def _cells_xz(stage1: dict[str, object], key: str, dict_form: bool) -> NDArray[np.float64]:
    """Read a stage-1 layer (``wall_cells`` dict form or ``floor_cells`` list form)."""
    layers = stage1.get("layers", {})
    assert isinstance(layers, dict)
    raw = layers.get(key) or []
    if not raw:
        return np.empty((0, 2), dtype=np.float64)
    if dict_form:
        return np.array([[float(c["x"]), float(c["z"])] for c in raw], dtype=np.float64)
    return np.array([[float(a), float(b)] for a, b in raw], dtype=np.float64)


def _room_out(room: Room, theta: float) -> dict[str, object]:
    """Serialise a room (uv polygon + world polygon + measurements)."""
    poly_world = [list(uv_to_world(u, v, theta)) for u, v in room.polygon_uv]
    key: dict[str, object] = {}
    for e in room.wall_lengths:
        key.setdefault(str(e["provenance"]), 0.0)
        key[str(e["provenance"])] = round(
            float(key[str(e["provenance"])]) + float(e["length_m"]), 4
        )
    return {
        "id": room.id,
        "status": room.status,
        "area": {
            "value": round(room.area_m2, 4),
            "unit": "m2",
            "ci_low": round(room.area_ci[0], 4),
            "ci_high": round(room.area_ci[1], 4),
            "method": "shoelace_montecarlo",
        },
        "perimeter": {
            "observed_m": round(room.perimeter_observed_m, 4),
            "total_m": round(room.perimeter_total_m, 4),
            "observed_frac": round(room.perimeter_observed_m / room.perimeter_total_m, 4)
            if room.perimeter_total_m
            else 0.0,
        },
        "length_by_provenance_m": key,
        "wall_lengths": room.wall_lengths,
        "ceiling": room.ceiling,
        "polygon_uv": [[round(u, 4), round(v, 4)] for u, v in room.polygon_uv],
        "polygon_world": [[round(x, 4), round(z, 4)] for x, z in poly_world],
        "region_cells": room.cells,
    }


def _cam_cell_set(cam_uv: NDArray[np.float64], grid: Grid) -> set[tuple[int, int]]:
    """The set of grid cells on the camera path."""
    if cam_uv.size == 0:
        return set()
    ci, cj = grid.ij_array(cam_uv[:, 0], cam_uv[:, 1])
    ok = (ci >= 0) & (ci < grid.nx) & (cj >= 0) & (cj < grid.nz)
    return {(int(a), int(b)) for a, b in zip(ci[ok], cj[ok], strict=True)}


def _domain_mask(
    grid: Grid,
    wall_uv: NDArray[np.float64],
    floor_uv: NDArray[np.float64],
    cam_uv: NDArray[np.float64],
    bin_m: float,
) -> NDArray[np.bool_]:
    """The observed-footprint domain: wall lines + floor/camera evidence bins, filled.

    Stage-1 floor/camera cells are ``bin_m`` apart, so each is filled as its whole bin;
    a light closing then a hole fill makes the footprint solid, so a flood fill separates
    rooms only at the walls (not at the gaps between evidence cells).
    """
    wall_mask = np.zeros((grid.nx, grid.nz), dtype=bool)
    floor_mask = np.zeros((grid.nx, grid.nz), dtype=bool)
    cam_mask = np.zeros((grid.nx, grid.nz), dtype=bool)
    _mark_cells(wall_mask, grid, wall_uv)
    _fill_bins(floor_mask, grid, floor_uv, bin_m)
    _fill_bins(cam_mask, grid, cam_uv, bin_m)
    union = wall_mask | floor_mask | cam_mask
    closed = ndimage.binary_closing(union, iterations=1)
    return ndimage.binary_fill_holes(closed) | wall_mask


def _make_room(
    reg: Region,
    grid: Grid,
    closed: list[WallPiece],
    nodes_uv: NDArray[np.float64],
    points_xyz: NDArray[np.float64] | None,
    theta: float,
    floor_y: float,
    p: RoomParams,
) -> Room | None:
    """Build a room from a region: polygon, edges, area, MC intervals, wall lengths, ceiling."""
    corners = region_polygon(reg.cells)
    if len(corners) < 3:
        return None
    edges, polygon_uv = simplify_polygon(corners, grid, closed, p.node_merge_m, p.min_step_m)
    if len(edges) < 4 or len(polygon_uv) < 4:
        return None
    area = polygon_area(polygon_uv)
    area_ci, len_ci = monte_carlo_room(edges, p)
    wl = wall_lengths(edges, len_ci, nodes_uv, p)
    total = sum(e.end - e.start for e in edges)
    obs = sum(e.end - e.start for e in edges if e.provenance == OBSERVED)
    indices = sorted({e.provenance for e in edges})
    ceiling = room_ceiling(polygon_uv, points_xyz, theta, floor_y, p)
    return Room(
        id="",
        status=reg.status,
        indices=indices,
        polygon_uv=polygon_uv,
        edges=edges,
        area_m2=area,
        area_ci=area_ci,
        perimeter_observed_m=obs,
        perimeter_total_m=total,
        wall_lengths=wl,
        cells=len(reg.cells),
        ceiling=ceiling,
        region_cells=set(reg.cells),
    )


def _rebuild_room(
    room: Room,
    corners_uv: list[tuple[float, float]],
    closed: list[WallPiece],
    nodes_uv: NDArray[np.float64],
    p: RoomParams,
) -> Room:
    """Re-derive a room's edges/area/CI/wall lengths after its polygon changed."""
    edges = _collapse_parallel(_edges_from_uv(corners_uv, closed))
    if len(edges) < 4:
        return room
    area_ci, len_ci = monte_carlo_room(edges, p)
    wl = wall_lengths(edges, len_ci, nodes_uv, p)
    total = sum(e.end - e.start for e in edges)
    obs = sum(e.end - e.start for e in edges if e.provenance == OBSERVED)
    return Room(
        id=room.id,
        status=room.status,
        indices=sorted({e.provenance for e in edges}),
        polygon_uv=corners_uv,
        edges=edges,
        area_m2=polygon_area(corners_uv),
        area_ci=area_ci,
        perimeter_observed_m=obs,
        perimeter_total_m=total,
        wall_lengths=wl,
        cells=room.cells,
        ceiling=room.ceiling,
        region_cells=room.region_cells,
    )


def _cells_in(poly: Polygon, cells: set[tuple[int, int]], grid: Grid) -> int:
    """How many region cells (centres) fall inside a uv polygon."""
    if not cells or poly.is_empty:
        return 0
    uv = np.array([grid.uv(i, j) for i, j in sorted(cells)], dtype=np.float64)
    inside = shapely.contains_xy(poly, uv[:, 0], uv[:, 1])
    return int(inside.sum())


def resolve_overlaps(
    rooms: list[Room],
    closed: list[WallPiece],
    nodes_uv: NDArray[np.float64],
    grid: Grid,
    p: RoomParams,
) -> tuple[list[Room], list[dict[str, object]]]:
    """Make room polygons simple and disjoint (fix 1).

    Each overlapping pair is resolved once, deterministically: the intersection is
    assigned to the room whose region owns more of it (ties -> the larger room) and
    subtracted from the other, whose polygon/edges/area are then re-derived. A
    second pass catches overlaps reintroduced by the first. Polygons that are not
    simple are repaired by ``buffer(0)`` first, so ``no_overlap`` can pass.
    """
    report: list[dict[str, object]] = []
    tol = p.overlap_tol_m2
    for i, r in enumerate(rooms):
        poly = Polygon(r.polygon_uv)
        if not poly.is_valid:
            corners = _ring_to_corners(poly.buffer(0))
            if len(corners) >= 4:
                rooms[i] = _rebuild_room(r, corners, closed, nodes_uv, p)
    for _ in range(2):
        changed = False
        n = len(rooms)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = Polygon(rooms[i].polygon_uv), Polygon(rooms[j].polygon_uv)
                if not a.is_valid or not b.is_valid:
                    continue
                inter = a.intersection(b)
                if inter.is_empty or float(inter.area) <= tol:
                    continue
                ci = _cells_in(inter, rooms[i].region_cells, grid)
                cj = _cells_in(inter, rooms[j].region_cells, grid)
                loser = j if (ci, rooms[i].area_m2) >= (cj, rooms[j].area_m2) else i
                winner = i if loser == j else j
                keep = a if loser == i else b
                corners = _ring_to_corners(keep.difference(inter))
                if len(corners) < 4:
                    continue
                rooms[loser] = _rebuild_room(rooms[loser], corners, closed, nodes_uv, p)
                report.append(
                    {
                        "rooms": [rooms[winner].id, rooms[loser].id],
                        "overlap_m2": round(float(inter.area), 6),
                        "assigned_to": rooms[winner].id,
                    }
                )
                changed = True
        if not changed:
            break
    return rooms, report


def region_inradius(cells: set[tuple[int, int]], grid: Grid) -> float:
    """Max inscribed-circle radius (m) of a region (distance transform on its bbox)."""
    if not cells:
        return 0.0
    ii = [c[0] for c in cells]
    jj = [c[1] for c in cells]
    i0, i1, j0, j1 = min(ii), max(ii), min(jj), max(jj)
    mask = np.zeros((i1 - i0 + 1, j1 - j0 + 1), dtype=bool)
    for i, j in cells:
        mask[i - i0, j - j0] = True
    return float(ndimage.distance_transform_edt(mask).max()) * grid.cell


def _boundary_contacts(regions: list[Region]) -> dict[tuple[int, int], int]:
    """Cell contacts between region pairs across the wall barrier (longest boundary)."""
    by_cell: dict[tuple[int, int], int] = {}
    for k, r in enumerate(regions):
        for c in r.cells:
            by_cell[c] = k
    contacts: dict[tuple[int, int], int] = {}
    for (i, j), k in by_cell.items():
        for gap in (1, 2, 3):
            for di, dj in ((gap, 0), (-gap, 0), (0, gap), (0, -gap)):
                k2 = by_cell.get((i + di, j + dj))
                if k2 is not None and k2 != k:
                    key = (min(k, k2), max(k, k2))
                    contacts[key] = contacts.get(key, 0) + 1
    return contacts


def apply_min_room_rule(
    regions: list[Region], grid: Grid, p: RoomParams
) -> tuple[list[Region], list[dict[str, object]]]:
    """Merge or reclassify regions too small/thin to be rooms (fix 2).

    A region that fails ``min_room_area_m2`` or ``min_room_inradius_m`` is merged
    into the neighbour it shares the longest boundary with (deterministically: the
    smallest failing region first, ties by index); if it has no neighbour - or the
    merge still fails - it becomes ``non_room_fragment`` and is not emitted as a
    room. Merging only ever grows a region, so the pass terminates.

    Region indices stay stable (a merged-away region becomes a tombstone), and the
    area/inradius/boundary-contact bookkeeping is cached and updated incrementally.
    """
    n = len(regions)
    if n == 0:
        return regions, []
    cell2 = grid.cell * grid.cell
    area = [len(r.cells) * cell2 for r in regions]
    inrad: dict[int, float] = {}
    alive = [True] * n
    contacts = _boundary_contacts(regions)
    report: list[dict[str, object]] = []

    def _inrad(k: int) -> float:
        if k not in inrad:
            inrad[k] = region_inradius(regions[k].cells, grid)
        return inrad[k]

    def _fails(k: int) -> bool:
        # Area is O(1); the (distance-transform) inradius is computed only when needed.
        return area[k] < p.min_room_area_m2 or _inrad(k) < p.min_room_inradius_m

    for _ in range(n + 1):
        failing = [
            (area[k], k) for k in range(n) if alive[k] and regions[k].status == "room" and _fails(k)
        ]
        if not failing:
            break
        _, k = min(failing)
        neighbours = sorted(
            (
                (other, c)
                for (a, b), c in contacts.items()
                if k in (a, b) and alive[other := (b if a == k else a)]
            ),
            key=lambda t: (-t[1], t[0]),
        )
        small = regions[k]
        if not neighbours:
            small.status = "non_room_fragment"
            report.append(
                {
                    "region": small.id,
                    "cells": len(small.cells),
                    "area_m2": round(area[k], 4),
                    "inradius_m": round(_inrad(k), 4),
                    "reason": "no_neighbour",
                }
            )
            alive[k] = False
            continue
        tgt, boundary_cells = neighbours[0]
        big = regions[tgt]
        big.cells |= small.cells
        big.has_camera = big.has_camera or small.has_camera
        big.status = "room" if big.has_camera else "unobserved_enclosed"
        area[tgt] += area[k]
        inrad[tgt] = region_inradius(big.cells, grid)
        report.append(
            {
                "region": small.id,
                "merged_into": big.id,
                "cells": len(small.cells),
                "area_m2": round(area[k], 4),
                "inradius_m": round(_inrad(k), 4),
                "boundary_cells": boundary_cells,
            }
        )
        # Redirect the merged region's contacts onto its target, drop its own.
        for key in [key for key in contacts if k in key]:
            count = contacts.pop(key)
            other = key[0] if key[1] == k else key[1]
            if other == tgt or not alive[other]:
                continue
            nk = (min(tgt, other), max(tgt, other))
            contacts[nk] = contacts.get(nk, 0) + count
        small.cells = set()
        small.status = "merged"
        alive[k] = False
    return regions, report


def polygon_inradius(corners: list[tuple[float, float]]) -> float:
    """Max inscribed-circle radius (m) of a uv polygon (deterministic binary search)."""
    if len(corners) < 3:
        return 0.0
    poly = Polygon(corners)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.buffer(-1e-6).is_empty:
        return 0.0
    hi = 1.0
    while not poly.buffer(-hi).is_empty and hi < 64.0:
        hi *= 2.0
    lo = 0.0
    for _ in range(20):
        mid = (lo + hi) / 2.0
        if poly.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return lo


def build_stage3(
    stage1: dict[str, object],
    stage2: dict[str, object],
    cfg: Config,
    *,
    floor_y: float = 0.0,
    points_xyz: NDArray[np.float64] | None = None,
) -> dict[str, object]:
    """Stage 3 entry point: closure -> rooms -> per-room measurements -> openings.

    Pure function of (frozen stage-1 evidence, stage-2 walls, config, floor_y, cloud).
    Deterministic: fixed ordering, ties by position, fixed RNG seed, rounded output.
    Never raises on degenerate input (results-out policy) - warnings are reported.
    """
    p = room_params_from_config(cfg)
    warnings: list[str] = []
    theta = math.radians(float(stage2.get("manhattan_angle_deg", 0.0) or 0.0))
    walls = _walls_from_stage2(stage2)
    all_xz = _cells_xz(stage1, "wall_cells", True)
    floor_xz = _cells_xz(stage1, "floor_cells", False)
    raw_cam = stage1.get("camera_xz") or []
    cam_xz = (
        np.array([[float(a), float(b)] for a, b in raw_cam], dtype=np.float64)
        if raw_cam
        else np.empty((0, 2), dtype=np.float64)
    )
    wall_uv = rotate_uv(all_xz, theta)
    floor_uv = rotate_uv(floor_xz, theta)
    cam_uv = rotate_uv(cam_xz, theta)
    pts_for_grid = np.vstack([wall_uv, floor_uv]) if (wall_uv.size or floor_uv.size) else wall_uv
    grid = build_grid(pts_for_grid, p.grid_m)
    domain = _domain_mask(grid, wall_uv, floor_uv, cam_uv, p.evidence_bin_m)

    closed, closures, score = close_walls(walls, wall_uv, floor_uv, cam_uv, grid, p)
    cam_cells = _cam_cell_set(cam_uv, grid)
    raw_regions = build_regions(closed, grid, domain, cam_uv, p)
    regions, waists = split_regions(raw_regions, grid, cam_cells, p)
    regions, min_room_merges = apply_min_room_rule(regions, grid, p)

    nodes = stage2.get("graph", {})
    node_uv: NDArray[np.float64] = np.empty((0, 2))
    if isinstance(nodes, dict):
        node_uv = np.array(
            [[float(n["uv"][0]), float(n["uv"][1])] for n in nodes.get("nodes", [])],
            dtype=np.float64,
        )

    rooms: list[Room] = []
    enclosed: list[dict[str, object]] = []
    fragments: list[dict[str, object]] = []
    for reg in regions:
        if reg.status in ("discarded", "merged") or not reg.cells:
            continue
        if reg.status == "non_room_fragment":
            fragments.append(
                {
                    "region": reg.id,
                    "cells": len(reg.cells),
                    "area_m2": round(len(reg.cells) * grid.cell * grid.cell, 4),
                    "reason": "below_min_room",
                }
            )
            continue
        if reg.status == "unobserved_enclosed":
            corners = region_polygon(reg.cells)
            world = [list(uv_to_world(*grid.uv(i, j), theta)) for i, j in corners]
            enclosed.append(
                {
                    "cells": len(reg.cells),
                    "polygon_world": [[round(x, 4), round(z, 4)] for x, z in world],
                    "note": "no camera; no dimensions emitted",
                }
            )
            continue
        room = _make_room(reg, grid, closed, node_uv, points_xyz, theta, floor_y, p)
        if room is None:
            continue
        if (
            room.area_m2 < p.min_room_area_m2
            or polygon_inradius(room.polygon_uv) < p.min_room_inradius_m
        ):
            fragments.append(
                {
                    "region": reg.id,
                    "cells": room.cells,
                    "area_m2": round(room.area_m2, 4),
                    "reason": "polygon_below_gate",
                }
            )
            continue
        rooms.append(room)

    rooms, overlap_report = resolve_overlaps(rooms, closed, node_uv, grid, p)
    rooms = [r for r in rooms if r.area_m2 > 0.0]
    rooms.sort(key=lambda r: (-r.area_m2, min(r.polygon_uv)))
    for k, room in enumerate(rooms):
        room.id = f"room_{k + 1}"
    enclosed.sort(key=lambda d: -int(d["cells"]))  # type: ignore[arg-type]
    for k, e in enumerate(enclosed):
        e["id"] = f"room_unobserved_{k + 1}"

    s2_open = stage2.get("openings") or []
    assert isinstance(s2_open, list)
    openings = build_openings(s2_open, waists, rooms)
    adj = adjacency(openings)
    closures_out = [
        {
            "axis": "u" if c.axis == 0 else "v",
            "offset_m": round(c.offset, 4),
            "start_m": round(c.start, 4),
            "end_m": round(c.end, 4),
            "kind": c.kind,
            "assumed_length_m": c.assumed_length_m,
            "cost": c.cost,
            "provenance": c.provenance,
        }
        for c in closures
    ]
    counts: dict[str, int] = {}
    for c in closures:
        counts[c.kind] = counts.get(c.kind, 0) + 1
    if not rooms:
        warnings.append("no rooms found (no camera region was enclosed)")
    return {
        "name": "rooms",
        "params": {
            "grid_m": p.grid_m,
            "room_min_area_m2": p.room_min_area_m2,
            "closure_max_m": p.closure_max_m,
            "closure_wall_tol_m": p.closure_wall_tol_m,
            "closure_bonus_m": p.closure_bonus_m,
            "closure_floor_penalty": p.closure_floor_penalty,
            "waist_min_m": p.waist_min_m,
            "waist_max_m": p.waist_max_m,
            "mc_samples": p.mc_samples,
            "ceiling_min_above_floor_m": p.ceiling_min_above_floor_m,
            "ceiling_prior_low_m": p.ceiling_prior_low_m,
            "ceiling_prior_high_m": p.ceiling_prior_high_m,
            "seed": p.seed,
            "calibration": "uncalibrated (plan 04f/08)",
        },
        "manhattan_angle_deg": round(math.degrees(theta), 3),
        "plan_score": score,
        "closure_counts": counts,
        "closures": closures_out,
        "waists": [
            {
                "axis": "u" if w.axis == 0 else "v",
                "offset_m": round(w.offset, 4),
                "start_m": round(w.start, 4),
                "end_m": round(w.end, 4),
                "width_m": round(w.width_m, 4),
                "provenance": w.provenance,
            }
            for w in waists
        ],
        "room_count": len(rooms),
        "rooms": [_room_out(r, theta) for r in rooms],
        "non_room_fragments": fragments,
        "min_room_merges": min_room_merges,
        "overlap_resolved": overlap_report,
        "unobserved_enclosed": enclosed,
        "openings": [
            {
                "id": o.id,
                "axis": "u" if o.axis == 0 else "v",
                "offset_m": round(o.offset, 4),
                "start_m": round(o.start, 4),
                "end_m": round(o.end, 4),
                "width_m": round(o.width_m, 4),
                "kind": o.kind,
                "rooms": list(o.rooms) if o.rooms else None,
                "provenance": o.provenance,
            }
            for o in openings
        ],
        "adjacency": adj,
        "theta_rad": theta,
        "warnings": warnings,
    }
