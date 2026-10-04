"""Build CIR surface/opening geometry from the stage-3 payload (I2).

Stage 3 emits rooms as uv polygons + ``wall_lengths`` (axis/offset/start/end) and
openings with the two rooms they join. Both the stitcher (S4, 04d) and the damage
layer (S5-S7, 04e) need real geometry, not empty placeholders, so this module
converts:

- each ``wall_lengths`` entry into a :class:`scan2plan.cir.Surface` with a world
  2-point polygon and an **inward-facing** horizontal plane (the plane sign is
  what lets the stitcher pair opposing connector walls); and
- each two-room opening into **two** :class:`scan2plan.cir.Opening` records (one
  per room, keyed to that room's nearest wall) so ``match_connectors`` can pair
  the same physical door seen from both sides.

Deterministic: rooms/walls are taken in the stage-3 (already sorted) order.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from scan2plan.cir import Measurement, Opening, Plane, Surface, Tier
from scan2plan.geometry.rooms import uv_to_world
from scan2plan.util.logging import get_logger

logger = get_logger("scan2plan.geometry.plan_geometry")


def _wall_world(
    axis: str, offset: float, start: float, end: float, theta: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    """World (x, z) endpoints of a uv wall line segment."""
    if axis == "u":  # u = offset (constant), v spans [start, end]
        return uv_to_world(offset, start, theta), uv_to_world(offset, end, theta)
    return uv_to_world(start, offset, theta), uv_to_world(end, offset, theta)


def _inward_plane(
    a: tuple[float, float], b: tuple[float, float], centroid: tuple[float, float]
) -> Plane | None:
    """Horizontal plane through a wall, normal oriented toward the room centroid."""
    dx, dz = b[0] - a[0], b[1] - a[1]
    n = (-dz, dx)
    length = float(np.hypot(n[0], n[1]))
    if length < 1e-9:
        return None
    nx, nz = n[0] / length, n[1] / length
    if nx * (centroid[0] - a[0]) + nz * (centroid[1] - a[1]) < 0.0:
        nx, nz = -nx, -nz
    d = -(nx * a[0] + nz * a[1])
    return Plane(normal=[nx, 0.0, nz], d=d)


def build_wall_surfaces(stage3: dict[str, object]) -> list[Surface]:
    """One :class:`Surface` per stage-3 wall segment, with geometry + plane."""
    theta = float(stage3.get("theta_rad", 0.0) or 0.0)
    rooms = stage3.get("rooms") or []
    assert isinstance(rooms, list)
    surfaces: list[Surface] = []
    for r in rooms:
        rid = str(r["id"])
        poly = r.get("polygon_world") or []
        if not poly:
            continue
        cx = sum(float(p[0]) for p in poly) / len(poly)
        cz = sum(float(p[1]) for p in poly) / len(poly)
        for k, wl in enumerate(r["wall_lengths"], start=1):
            a, b = _wall_world(
                str(wl["axis"]),
                float(wl["offset_m"]),
                float(wl["start_m"]),
                float(wl["end_m"]),
                theta,
            )
            plane = _inward_plane(a, b, (cx, cz))
            surfaces.append(
                Surface(
                    id=f"{rid}_wall_{k}",
                    room_id=rid,
                    type="wall",
                    plane=plane,
                    polygon=[[round(a[0], 4), round(a[1], 4)], [round(b[0], 4), round(b[1], 4)]],
                )
            )
    return surfaces


def _seg_distance(p: tuple[float, float], a: list[float], b: list[float]) -> float:
    """Point-to-segment distance in the XZ plane."""
    px, pz = p
    ax, az, bx, bz = float(a[0]), float(a[1]), float(b[0]), float(b[1])
    dx, dz = bx - ax, bz - az
    denom = dx * dx + dz * dz
    if denom < 1e-12:
        return float(np.hypot(px - ax, pz - az))
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / denom))
    return float(np.hypot(px - (ax + t * dx), pz - (az + t * dz)))


def _meas(mid: str, kind: str, value: float, method: str, tier: Tier, *, rel: float) -> Measurement:
    """A Measurement whose interval is ``value * (1 +/- rel)`` (contains the value)."""
    v = max(0.0, float(value))
    return Measurement(
        id=mid,
        kind=kind,
        value=round(v, 4),
        unit="m",
        ci_low=round(max(0.0, v * (1.0 - rel)), 4),
        ci_high=round(v * (1.0 + rel), 4),
        method=method,
        tier=tier,
    )


def build_connector_openings(
    stage3: dict[str, object],
    surfaces: list[Surface],
    *,
    tier: Tier,
    width_rel_ci: float = 0.10,
) -> list[Opening]:
    """Two ``Opening`` records (one per room) per two-room stage-3 opening."""
    theta = float(stage3.get("theta_rad", 0.0) or 0.0)
    rooms = stage3.get("rooms") or []
    assert isinstance(rooms, list)
    room_ceiling = {str(r["id"]): float(r["ceiling"]["value"]) for r in rooms if r.get("ceiling")}
    by_room: dict[str, list[Surface]] = defaultdict(list)
    for s in surfaces:
        by_room[s.room_id].append(s)
    out: list[Opening] = []
    for o in stage3.get("openings") or []:
        joins = o.get("rooms")
        if not joins or len(joins) < 2:
            continue
        a, b = _wall_world(
            str(o["axis"]), float(o["offset_m"]), float(o["start_m"]), float(o["end_m"]), theta
        )
        mid = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))
        width = float(o["width_m"])
        kind = str(o["kind"])
        for side, rid in (("a", str(joins[0])), ("b", str(joins[1]))):
            candidates = by_room.get(rid, [])
            if not candidates:
                continue
            host = min(
                candidates,
                key=lambda s: _seg_distance(mid, s.polygon[0], s.polygon[1]),
            )
            ceil = room_ceiling.get(rid, 2.4)
            oid = f"{o['id']}_{side}"
            out.append(
                Opening(
                    id=oid,
                    room_id=rid,
                    surface_id=host.id,
                    kind=kind,  # type: ignore[arg-type]
                    width=_meas(
                        f"{oid}.width",
                        "opening_width",
                        width,
                        "camera_path_cross",
                        tier,
                        rel=width_rel_ci,
                    ),
                    height=_meas(f"{oid}.height", "opening_height", ceil, "prior", tier, rel=0.05),
                    detection_confidence=0.6,
                )
            )
    return out
