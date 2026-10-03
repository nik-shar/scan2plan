"""Concave (polygonal) room footprint from floor points (plan 04h, tasks G-6/G-7).

The M3 OBB model (04c) can only represent rectangles, so an L-shaped room (e.g. a
main room with an attached bathroom) gets an inflated area and its real walls -
including the one holding the door - are never scanned by the opening detector.
This module extracts the room's true concave outline as a rectilinear polygon:

  floor points -> Manhattan rotation -> 5 cm occupancy grid -> morphological
  cleanup (close gaps, fill holes, keep the largest component) -> union of the
  occupied cells (shapely) -> simplify + collinear merge -> CCW ring.

Everything here is deterministic (no RNG). Callers fall back to the OBB path when
``extract_footprint`` returns ``None`` (results-out policy, plan 04 section 3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

GRID_BIN_M = 0.10
SIMPLIFY_M = 0.12
MIN_AREA_M2 = 2.0
MIN_EDGE_M = 0.20
MIN_RING_POINTS = 3
COLLINEAR_TOL_DEG = 8.0
#: Chord tolerance for the "remove sub-resolution jogs" pass. Set above the grid
#: cell size (a boundary landing on a cell edge produces a ~2-cell step) but at
#: MIN_EDGE_M so genuine wall features are never removed.
CHORD_TOL_M = 0.20
CLOSE_ITERATIONS = 2
#: Complexity cap: ragged real-floor boundaries are simplified further (tolerance
#: grown until the ring fits) so the plan does not emit dozens of micro-walls.
MAX_RING_POINTS = 16
MAX_SIMPLIFY_M = 1.0
TRIM_PCT_LO = 0.5
TRIM_PCT_HI = 99.5


def rotate2d(xz: NDArray[np.float64], theta: float) -> NDArray[np.float64]:
    """Rotate 2D points (Nx2) by ``theta`` radians (the Manhattan alignment)."""
    c, s = float(np.cos(theta)), float(np.sin(theta))
    rot = np.array([[c, -s], [s, c]])
    return np.asarray(xz @ rot.T, dtype=np.float64)


@dataclass(frozen=True)
class Footprint2D:
    """A room footprint: a simplified CCW ring in the rotated-local frame + area."""

    ring_local: NDArray[np.float64]  # (N, 2), open ring (no repeated first point)
    area_m2: float


def occupancy_grid(
    rot: NDArray[np.float64], *, bin_m: float = GRID_BIN_M
) -> tuple[NDArray[np.bool_], float, float]:
    """Rasterise rotated floor points; returns (grid, x0, z0).

    ``grid`` is indexed ``[row=z, col=x]`` and ``(x0, z0)`` is the rotated-frame
    coordinate of cell (0, 0)'s lower corner. Points outside the 0.5-99.5%
    percentile box are trimmed first (drops detached outlier islands).
    """
    if rot.shape[0] == 0:
        return np.zeros((0, 0), dtype=bool), 0.0, 0.0
    lo, hi = np.percentile(rot, [TRIM_PCT_LO, TRIM_PCT_HI], axis=0)
    keep = np.all((rot >= lo) & (rot <= hi), axis=1)
    pts = rot[keep] if keep.any() else rot
    x0 = float(math.floor(float(pts[:, 0].min()) / bin_m) * bin_m) - 2.0 * bin_m
    z0 = float(math.floor(float(pts[:, 1].min()) / bin_m) * bin_m) - 2.0 * bin_m
    ncols = int(math.ceil((float(pts[:, 0].max()) - x0) / bin_m)) + 2
    nrows = int(math.ceil((float(pts[:, 1].max()) - z0) / bin_m)) + 2
    ix = np.clip(((pts[:, 0] - x0) / bin_m).astype(np.int64), 0, ncols - 1)
    iz = np.clip(((pts[:, 1] - z0) / bin_m).astype(np.int64), 0, nrows - 1)
    grid = np.zeros((nrows, ncols), dtype=bool)
    grid[iz, ix] = True
    return grid, x0, z0


def grid_to_polygon(
    grid: NDArray[np.bool_], x0: float, z0: float, bin_m: float
) -> NDArray[np.float64] | None:
    """Cells -> simplified CCW exterior ring of the largest component (or None)."""
    if grid.size == 0 or not grid.any():
        return None
    structure = np.ones((3, 3), dtype=bool)
    closed = ndimage.binary_closing(grid, structure=structure, iterations=CLOSE_ITERATIONS)
    # Opening removes single-cell teeth/notches where an axis-aligned edge lands on
    # a grid-cell boundary (the 1-cell staircase); it preserves real corners.
    opened = ndimage.binary_opening(closed, structure=structure, iterations=1)
    filled = ndimage.binary_fill_holes(opened)
    labels, n = ndimage.label(filled)
    if n == 0:
        return None
    sizes = ndimage.sum(np.ones_like(labels, dtype=np.float64), labels, index=range(1, n + 1))
    largest = int(np.argmax(sizes)) + 1
    if float(sizes[largest - 1]) * bin_m * bin_m < MIN_AREA_M2:
        return None

    rows, cols = np.nonzero(labels == largest)
    cells = [
        box(x0 + c * bin_m, z0 + r * bin_m, x0 + (c + 1) * bin_m, z0 + (r + 1) * bin_m)
        for r, c in zip(rows.tolist(), cols.tolist(), strict=True)
    ]
    merged = unary_union(cells)
    if merged.is_empty:
        return None
    poly = max(merged.geoms, key=lambda g: g.area) if merged.geom_type == "MultiPolygon" else merged
    poly = orient(poly.simplify(SIMPLIFY_M, preserve_topology=True), sign=1.0)
    coords = np.asarray(poly.exterior.coords[:-1], dtype=np.float64)  # drop closing dup
    return coords if coords.shape[0] >= MIN_RING_POINTS else None


def merge_collinear(
    ring: NDArray[np.float64],
    *,
    tol_deg: float = COLLINEAR_TOL_DEG,
    min_edge_m: float = MIN_EDGE_M,
    chord_tol_m: float = CHORD_TOL_M,
) -> NDArray[np.float64]:
    """Collapse near-collinear consecutive edges and edges shorter than ``min_edge_m``.

    Three passes, repeated until stable: (1) drop edges shorter than
    ``min_edge_m``; (2) merge neighbours whose directions differ by < ``tol_deg``;
    (3) drop any vertex lying within ``chord_tol_m`` of the chord between its
    neighbours (this removes the 1-cell staircase left where an axis-aligned edge
    lands exactly on a grid-cell boundary). Genuine corners survive because their
    chord distance is large.
    """
    pts: list[tuple[float, float]] = []
    for p in (tuple(map(float, q)) for q in ring):
        if not pts or abs(p[0] - pts[-1][0]) > 1e-9 or abs(p[1] - pts[-1][1]) > 1e-9:
            pts.append(p)
    if len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) < 1e-9 and abs(pts[0][1] - pts[-1][1]) < 1e-9:
        pts.pop()

    cos_tol = math.cos(math.radians(tol_deg))
    changed = True
    while changed and len(pts) > MIN_RING_POINTS:
        changed = False
        n = len(pts)
        edges = [
            (pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1]) for i in range(n)
        ]
        # 1. drop short edges by removing their far endpoint
        for i, (ex, ez) in enumerate(edges):
            if math.hypot(ex, ez) < min_edge_m:
                del pts[(i + 1) % n]
                changed = True
                break
        if changed:
            continue
        # 2. merge near-collinear neighbours by removing the shared vertex
        for i in range(n):
            u, v = edges[i], edges[(i + 1) % n]
            lu, lv = math.hypot(*u), math.hypot(*v)
            if lu < 1e-9 or lv < 1e-9:
                continue
            if (u[0] * v[0] + u[1] * v[1]) / (lu * lv) >= cos_tol:
                del pts[(i + 1) % n]
                changed = True
                break
        if changed:
            continue
        # 3. drop vertices within chord_tol_m of the chord between their neighbours
        for i in range(n):
            ax, az = pts[(i - 1) % n]
            px, pz = pts[i]
            bx, bz = pts[(i + 1) % n]
            dx, dz = bx - ax, bz - az
            chord = math.hypot(dx, dz)
            if chord < 1e-9:
                continue
            if abs((px - ax) * dz - (pz - az) * dx) / chord < chord_tol_m:
                del pts[i]
                changed = True
                break
    return np.asarray(pts, dtype=np.float64)


def cap_complexity(
    ring: NDArray[np.float64],
    *,
    max_points: int = MAX_RING_POINTS,
    max_tol_m: float = MAX_SIMPLIFY_M,
) -> NDArray[np.float64]:
    """Grow the simplification tolerance until the ring has <= ``max_points``.

    A clean synthetic room is already below the cap, so this only affects ragged
    real-floor boundaries (which would otherwise emit dozens of micro-walls). The
    tolerance is grown geometrically from ``SIMPLIFY_M`` up to ``max_tol_m``.
    """
    if ring.shape[0] <= max_points:
        return ring
    poly = Polygon(ring)
    tol = SIMPLIFY_M
    out = ring
    while out.shape[0] > max_points and tol <= max_tol_m:
        tol *= 1.5
        simplified = poly.simplify(tol, preserve_topology=True)
        if simplified.geom_type != "Polygon" or simplified.is_empty:
            break
        out = merge_collinear(np.asarray(simplified.exterior.coords[:-1]))
    return out


def extract_footprint(xz: NDArray[np.float64], theta: float) -> Footprint2D | None:
    """Full footprint pipeline (plan 04h section 4.2 steps 3-7); None => OBB fallback."""
    if xz.shape[0] < 4:
        return None
    grid, x0, z0 = occupancy_grid(rotate2d(xz, theta))
    raw = grid_to_polygon(grid, x0, z0, GRID_BIN_M)
    if raw is None:
        return None
    ring = cap_complexity(merge_collinear(raw))
    if ring.shape[0] < MIN_RING_POINTS:
        return None
    area = float(Polygon(ring).area)
    if area < MIN_AREA_M2:
        return None
    return Footprint2D(ring_local=ring, area_m2=area)
