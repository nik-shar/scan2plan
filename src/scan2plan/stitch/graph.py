"""Room graph + connector matching (plan 04d sections 2.1-2.2, task S-1).

Nodes are rooms; candidate edges are shared **connectors** (doors/passages) found
by S3. A door between room A and room B is one physical opening seen from both
sides, so the two `Opening` records must agree on width and their host wall
planes must coincide with **opposing** normals. A match yields a relative SE(2)
constraint ``T_ab`` (room A's frame expressed in room B's frame).

Known limitation (I2 gap, to be raised via ADR if it binds): ``Opening`` carries
no along-wall offset, so the transform aligns the host-wall **midpoints**; the
along-wall error is bounded by half the wall-length difference and is absorbed by
the pose-graph optimization (04d section 2.4) when other constraints exist.
"""

from __future__ import annotations

import math

from scan2plan.cir import SE2, Opening, Room, StitchEdge, Surface
from scan2plan.stitch.se2 import wrap_angle

#: Kinds that can connect two rooms (windows never do; 04c section 3).
CONNECTOR_KINDS = frozenset({"door", "passage"})

#: Base width agreement for two openings to be the same physical connector;
#: widened by the openings' own CI half-widths (I6 honest-uncertainty policy).
WIDTH_TOL_M = 0.06


def wall_pose(surface: Surface) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Wall midpoint + unit normal in the room frame (plan XY = world X/Z, I7).

    Falls back to the polygon-edge perpendicular when the surface has no plane.
    Returns None for degenerate polygons.
    """
    if len(surface.polygon) < 2:
        return None
    a, b = surface.polygon[0], surface.polygon[1]
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    if surface.plane is not None:
        nx, ny = surface.plane.normal[0], surface.plane.normal[2]
    else:
        dx, dy = b[0] - a[0], b[1] - a[1]
        nx, ny = -dy, dx
    n = math.hypot(nx, ny)
    if n < 1e-9:
        return None
    return mid, (nx / n, ny / n)


def connector_transform(
    a_pose: tuple[tuple[float, float], tuple[float, float]],
    b_pose: tuple[tuple[float, float], tuple[float, float]],
) -> SE2:
    """Relative transform A->B aligning wall midpoints with opposing normals."""
    (ma, na), (mb, nb) = a_pose, b_pose
    theta = wrap_angle(math.atan2(-nb[1], -nb[0]) - math.atan2(na[1], na[0]))
    c, s = math.cos(theta), math.sin(theta)
    return SE2(x=mb[0] - (c * ma[0] - s * ma[1]), y=mb[1] - (s * ma[0] + c * ma[1]), theta=theta)


def match_connectors(
    rooms: list[Room],
    surfaces: list[Surface],
    openings: list[Opening],
    *,
    width_tol_m: float = WIDTH_TOL_M,
) -> list[StitchEdge]:
    """Match connector openings across rooms into relative-pose edges.

    Width agreement: ``|w_a - w_b| <= max(width_tol_m, hw_a + hw_b)`` where ``hw``
    is the measurement CI half-width (thin data widens the match gate instead of
    failing hard, per the results-out policy). The edge weight is the inverse CI
    width so tight measurements dominate the optimization.
    """
    del rooms  # room context comes from the openings themselves
    surf_by_id = {s.id: s for s in surfaces}
    candidates = [
        o
        for o in openings
        if o.kind in CONNECTOR_KINDS and o.width is not None and o.surface_id in surf_by_id
    ]
    edges: list[StitchEdge] = []
    for i, oa in enumerate(candidates):
        for ob in candidates[i + 1 :]:
            if oa.room_id == ob.room_id:
                continue
            assert oa.width is not None and ob.width is not None  # narrowed above
            hw = oa.width.half_width + ob.width.half_width
            if abs(oa.width.value - ob.width.value) > max(width_tol_m, hw):
                continue
            pa = wall_pose(surf_by_id[oa.surface_id])
            pb = wall_pose(surf_by_id[ob.surface_id])
            if pa is None or pb is None:
                continue
            edges.append(
                StitchEdge(
                    room_a=oa.room_id,
                    room_b=ob.room_id,
                    transform=connector_transform(pa, pb),
                    kind="connector",
                    weight=round(1.0 / max(hw, 0.02), 3),
                )
            )
    return edges
