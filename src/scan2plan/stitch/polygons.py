"""Plan-view polygon operations for stitching (plan 04d sections 2.5-2.7).

Room boundaries are 2D polygons in the room frame (plan axes = world X/Z, I7).
Shapely provides the metric operations: pairwise interior overlap (the G-PSTITCH
``overlap_ok`` gate) and the union footprint area (the ablation metric, section 4).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import Polygon
from shapely.ops import unary_union

from scan2plan.cir import SE2, Room
from scan2plan.stitch.se2 import apply


def room_polygon(room: Room, transform: SE2 | None = None) -> Polygon:
    """The room's floor boundary as a shapely polygon, optionally SE(2)-transformed."""
    if transform is None:
        pts = [(p[0], p[1]) for p in room.boundary]
    else:
        pts = [apply(transform, p[0], p[1]) for p in room.boundary]
    return Polygon(pts)


def placed_polygons(rooms: list[Room], transforms: dict[str, SE2]) -> dict[str, Polygon]:
    """All room polygons placed in the plan frame by their stitch transforms."""
    return {r.id: room_polygon(r, transforms.get(r.id)) for r in rooms}


def pairwise_overlaps(polys: dict[str, Polygon]) -> dict[tuple[str, str], float]:
    """Interior intersection areas for every polygon pair (0-area touches excluded)."""
    out: dict[tuple[str, str], float] = {}
    ids = sorted(polys)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            area = float(polys[a].intersection(polys[b]).area)
            if area > 0.0:
                out[(a, b)] = area
    return out


def union_area(polys: dict[str, Polygon]) -> float:
    """Area of the union of all polygons (the stitched footprint, m2)."""
    if not polys:
        return 0.0
    return float(unary_union(list(polys.values())).area)


def boundary_points(poly: Polygon, step_m: float = 0.1) -> NDArray[np.float64]:
    """Evenly spaced points along the polygon exterior (for ICP loop closure)."""
    length = float(poly.exterior.length)
    n = max(8, int(length / step_m))
    ds = np.linspace(0.0, length, n, endpoint=False)
    return np.array(
        [[p.x, p.y] for p in (poly.exterior.interpolate(float(d)) for d in ds)],
        dtype=np.float64,
    )
