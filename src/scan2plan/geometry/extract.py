"""Turn a world point cloud into room/surface/opening CIR entities (plan 04c/04h).

Single-room scope: floor/ceiling planes -> **concave polygonal footprint** of the
floor (plan 04h; Manhattan-aligned, plan 04c section 1.2) -> one wall Surface per
polygon edge -> a first-cut door/passage detector (wall-gap analysis). The
oriented bounding box (OBB) is retained only as a fallback when the floor grid is
unusable, so rooms are no longer forced to be rectangles (L-shaped rooms keep
their real area and walls). Interior partitions and curved walls remain out of
scope (plan 04h non-goals).

Confidence intervals here are placeholder plane-RMS/relative margins; plan 04f
replaces them with calibrated (conformal) intervals at M6.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from scan2plan.cir import Measurement, Opening, Plane, Room, Surface
from scan2plan.cir.measure import Tier
from scan2plan.geometry.footprint import extract_footprint, rotate2d
from scan2plan.geometry.planes import HorizontalPlane, horizontal_planes

# Opening detection thresholds (tunable; validated against ground truth at M7).
DOOR_MIN_WIDTH_M = 0.55
DOOR_MAX_WIDTH_M = 1.6
WALL_SLAB_M = 0.08  # points within this of a wall plane count as "on the wall"
DOOR_SCAN_HEIGHT_M = 2.2  # look for openings up to this height above the floor
MIN_WALL_LEN_M = 0.30  # polygon edges shorter than this are not emitted as walls

# Placeholder CI half-widths (replaced by calibrated CIs in 04f / M6).
CEIL_CI_K = 3.0  # half-width = CEIL_CI_K * (floor_rms + ceiling_rms)
AREA_CI_REL = 0.05
LENGTH_CI_M = 0.02
OPENING_CI_M = 0.02

# Robust (percentile) extents for the OBB so a few drifted/reflection outliers do
# not inflate the room. Walls are dense vertical planes, so 1-99% still sits on them.
OBB_PCT_LO = 1.0
OBB_PCT_HI = 99.0


@dataclass
class RoomGeometry:
    """The CIR entities produced for one room (S3 output)."""

    room: Room
    surfaces: list[Surface] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    measures: list[Measurement] = field(default_factory=list)


def _measurement(
    id: str,
    kind: str,
    value: float,
    unit: str,
    half_width: float,
    method: str,
    tier: Tier,
) -> Measurement:
    return Measurement(
        id=id,
        kind=kind,
        value=round(value, 4),
        unit=unit,
        ci_low=round(value - half_width, 4),
        ci_high=round(value + half_width, 4),
        method=method,
        tier=tier,
    )


def estimate_orientation(xz: NDArray[np.float64], step_deg: float = 1.0) -> float:
    """Manhattan orientation: yaw minimising the (robust) bounding-box area."""
    best_theta, best_area = 0.0, np.inf
    for deg in np.arange(0.0, 90.0, step_deg):
        theta = float(np.deg2rad(deg))
        rot = rotate2d(xz, theta)
        xs = np.percentile(rot[:, 0], [OBB_PCT_LO, OBB_PCT_HI])
        zs = np.percentile(rot[:, 1], [OBB_PCT_LO, OBB_PCT_HI])
        area = float((xs[1] - xs[0]) * (zs[1] - zs[0]))
        if area < best_area:
            best_area, best_theta = area, theta
    return best_theta


def _detect_openings(
    points: NDArray[np.float64],
    walls: list[tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]],
    floor_y: float,
    wall_ids: list[str],
    room_id: str,
    tier: Tier,
) -> list[Opening]:
    """Find door/passage gaps on each wall via along-wall density at floor level."""
    openings: list[Opening] = []
    for wall_id, (a3, b3, _n) in zip(wall_ids, walls, strict=True):
        a = a3[[0, 2]]
        b = b3[[0, 2]]
        d = b - a
        length = float(np.hypot(d[0], d[1]))
        if length < 1e-6:
            continue
        t_dir = d / length
        # distance of each point to the wall's vertical plane (normal = _n)
        n2 = _n[[0, 2]]
        n2 = n2 / np.linalg.norm(n2)
        rel = points[:, [0, 2]] - a
        dist = rel @ n2  # signed perpendicular distance
        on_wall = np.abs(dist) <= WALL_SLAB_M
        # Wall body band: above the floor slab (which continues through a doorway)
        # and below the header. A door/passage is a full-height gap in this band.
        band = (points[:, 1] >= floor_y + 0.2) & (points[:, 1] <= floor_y + DOOR_SCAN_HEIGHT_M)
        mask = on_wall & band
        if not mask.any():
            continue
        t = (points[mask][:, [0, 2]] - a) @ t_dir  # along-wall coordinate
        # along-wall occupancy histogram
        bin_w = 0.05
        bins = np.arange(0.0, length + bin_w, bin_w)
        counts, _ = np.histogram(t, bins=bins)
        occupied = counts > 0
        # contiguous empty interior runs -> candidate gaps
        i = 0
        while i < len(occupied):
            if occupied[i]:
                i += 1
                continue
            j = i
            while j < len(occupied) and not occupied[j]:
                j += 1
            gap_lo, gap_hi = bins[i], bins[j]
            gap_w = gap_hi - gap_lo
            interior = i > 0 and j < len(occupied)
            if interior and DOOR_MIN_WIDTH_M <= gap_w <= DOOR_MAX_WIDTH_M:
                # confidence: how empty the gap is vs. the wall's occupied density
                wall_density = counts[occupied].mean() if occupied.any() else 1.0
                conf = 1.0 - min(1.0, counts[i:j].mean() / (wall_density + 1e-9))
                openings.append(
                    Opening(
                        id=f"open_{room_id}_{len(openings) + 1}",
                        room_id=room_id,
                        surface_id=wall_id,
                        kind="door",
                        width=_measurement(
                            f"open_{room_id}_{len(openings) + 1}.width",
                            "opening_width",
                            gap_w,
                            "m",
                            OPENING_CI_M,
                            "wall_gap",
                            tier,
                        ),
                        detection_confidence=round(float(conf), 3),
                    )
                )
            i = j
    return openings


def _extract_obb_ring(
    rot: NDArray[np.float64],
) -> tuple[NDArray[np.float64], float]:
    """Fallback footprint: robust oriented bounding box (Manhattan frame).

    Returns the CCW rectangle corners (4x2) and its area (plan 04c section 1.2).
    """
    xs = np.percentile(rot[:, 0], [OBB_PCT_LO, OBB_PCT_HI])
    zs = np.percentile(rot[:, 1], [OBB_PCT_LO, OBB_PCT_HI])
    xmin, xmax = float(xs[0]), float(xs[1])
    zmin, zmax = float(zs[0]), float(zs[1])
    corners = np.array([[xmin, zmin], [xmax, zmin], [xmax, zmax], [xmin, zmax]], dtype=np.float64)
    return corners, (xmax - xmin) * (zmax - zmin)


def _walls_from_boundary(
    ring_local: NDArray[np.float64],
    theta: float,
    floor_y: float,
    room_id: str,
    tier: Tier,
    *,
    method: str,
) -> tuple[
    list[Surface],
    list[tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]],
    list[Measurement],
]:
    """One wall Surface + wall_length Measurement per CCW footprint edge.

    Outward normal of edge (a->b) is ``(dz, -dx)`` normalised (valid for a CCW
    ring). Edges shorter than ``MIN_WALL_LEN_M`` are skipped and do not consume a
    wall id. Returns the surfaces, the ``(a3, b3, n3)`` tuples for the opening
    detector, and the wall-length measurements.
    """
    surfaces: list[Surface] = []
    walls: list[tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]] = []
    measures: list[Measurement] = []
    n = ring_local.shape[0]
    for i in range(n):
        a_l = ring_local[i]
        b_l = ring_local[(i + 1) % n]
        dx, dz = float(b_l[0] - a_l[0]), float(b_l[1] - a_l[1])
        wall_len = float(math.hypot(dx, dz))
        if wall_len < MIN_WALL_LEN_M:
            continue
        n_local = np.array([dz, -dx], dtype=np.float64) / wall_len
        a_w = rotate2d(a_l[None, :], -theta)[0]
        b_w = rotate2d(b_l[None, :], -theta)[0]
        n_w = rotate2d(n_local[None, :], -theta)[0]
        n3 = np.array([float(n_w[0]), 0.0, float(n_w[1])])
        a3 = np.array([float(a_w[0]), floor_y, float(a_w[1])])
        b3 = np.array([float(b_w[0]), floor_y, float(b_w[1])])
        d = float(-(n3[0] * a3[0] + n3[2] * a3[2]))
        wall_id = f"{room_id}_wall_{len(surfaces) + 1}"
        surfaces.append(
            Surface(
                id=wall_id,
                room_id=room_id,
                type="wall",
                plane=Plane(normal=[n3[0], n3[1], n3[2]], d=d),
                polygon=[[float(a_w[0]), float(a_w[1])], [float(b_w[0]), float(b_w[1])]],
            )
        )
        measures.append(
            _measurement(
                f"{wall_id}.length", "wall_length", wall_len, "m", LENGTH_CI_M, method, tier
            )
        )
        walls.append((a3, b3, n3))
    return surfaces, walls, measures


def extract_room(
    points: NDArray[np.float64],
    *,
    tier: Tier,
    seed: int = 1337,
    room_id: str = "room_0",
    name: str | None = None,
) -> RoomGeometry:
    """Build the room + surfaces + openings from a world point cloud (S3)."""
    if points.size == 0:
        raise ValueError("empty point cloud")
    y = points[:, 1]
    planes = horizontal_planes(y)
    if not planes:
        raise ValueError("no floor plane detected")
    floor: HorizontalPlane = planes[0]
    ceiling: HorizontalPlane | None = planes[1] if len(planes) > 1 else None
    floor_y = floor.height_m

    # Floor footprint: concave polygon when the floor grid is usable (plan 04h),
    # else the robust oriented bounding box (plan 04c section 1.2, documented fallback).
    slab = points[np.abs(y - floor_y) <= 0.08]
    xz = slab[:, [0, 2]]
    if xz.shape[0] < 4:
        xz = points[:, [0, 2]]  # fallback: use all points if the floor slab is thin
    theta = estimate_orientation(xz)

    footprint = extract_footprint(xz, theta)
    if footprint is not None:
        ring_local = footprint.ring_local
        area_m2 = footprint.area_m2
        method = "polygon"
    else:
        ring_local, area_m2 = _extract_obb_ring(rotate2d(xz, theta))
        method = "obb"
    boundary = [[float(a), float(b)] for a, b in rotate2d(ring_local, -theta)]

    ceiling_height = None
    if ceiling is not None:
        ceil_h = ceiling.height_m - floor_y
        ceiling_height = _measurement(
            f"{room_id}.ceiling_height",
            "ceiling_height",
            ceil_h,
            "m",
            CEIL_CI_K * (floor.rms_m + ceiling.rms_m),
            "plane_fit",
            tier,
        )
    floor_area = _measurement(
        f"{room_id}.floor_area", "floor_area", area_m2, "m2", AREA_CI_REL * area_m2, "polygon", tier
    )

    room = Room(
        id=room_id,
        name=name,
        boundary=boundary,
        ceiling_height=ceiling_height,
        floor_area=floor_area,
    )

    # Walls: one Surface per footprint edge (L-shaped rooms => >4 walls).
    surfaces, walls, measures = _walls_from_boundary(
        ring_local, theta, floor_y, room_id, tier, method=method
    )
    wall_ids = [s.id for s in surfaces if s.type == "wall"]

    edges = np.roll(ring_local, -1, axis=0) - ring_local
    perimeter = float(np.sum(np.hypot(edges[:, 0], edges[:, 1])))
    measures.append(
        _measurement(
            f"{room_id}.perimeter", "perimeter", perimeter, "m", 2 * LENGTH_CI_M, method, tier
        )
    )

    surfaces.append(
        Surface(
            id=f"{room_id}_floor",
            room_id=room_id,
            type="floor",
            plane=Plane(normal=[0.0, 1.0, 0.0], d=float(-floor_y)),
            polygon=boundary,
        )
    )
    if ceiling is not None:
        surfaces.append(
            Surface(
                id=f"{room_id}_ceiling",
                room_id=room_id,
                type="ceiling",
                plane=Plane(normal=[0.0, -1.0, 0.0], d=float(ceiling.height_m)),
                polygon=boundary,
            )
        )

    openings = _detect_openings(points, walls, floor_y, wall_ids, room_id, tier)
    return RoomGeometry(room=room, surfaces=surfaces, openings=openings, measures=measures)
