"""CLI-facing stitch helpers (plan 04d S-5).

Thin wrappers so the pipeline can produce the CIR ``stitch{}`` block and the
G-DRIFT ablation from one code path. Rooms from a single capture already share
the stage-1 reconstruction frame, so initial placements are the identity; the
optimizer then reconciles connector/loop-closure constraints without inventing
motion (plan 04d section 3 - poses are never consumed as final geometry).
"""

from __future__ import annotations

from typing import Any

from scan2plan.cir import CIR, SE2, Room, Stitch
from scan2plan.config import Config
from scan2plan.stitch.core import run_ablation, run_stitch
from scan2plan.stitch.polygons import room_polygon

#: Two rooms whose floor polygons are within this distance share a wall.
ADJACENT_TOL_M = 0.05


def rooms_connected(rooms: list[Room], tol_m: float = ADJACENT_TOL_M) -> bool:
    """True when every room is reachable via shared/adjacent floor polygons.

    ``run_stitch`` reports ``unstitched`` from the *constraint* graph (connectors
    + loop closures), which is the wrong criterion for a single capture whose
    rooms are reconstructed in one shared frame: two rooms that share a wall are
    connected even if no door between them was detected.
    """
    ids = sorted(r.id for r in rooms)
    if len(ids) <= 1:
        return True
    polys = {r.id: room_polygon(r) for r in rooms}
    adj: dict[str, set[str]] = {i: set() for i in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if polys[a].distance(polys[b]) <= tol_m:
                adj[a].add(b)
                adj[b].add(a)
    seen: set[str] = set()
    stack = [ids[0]]
    while stack:
        r = stack.pop()
        if r in seen:
            continue
        seen.add(r)
        stack.extend(adj[r] - seen)
    return len(seen) == len(ids)


def stitch_plan(
    cir: CIR,
    cfg: Config,
    *,
    diagnostics: dict[str, Any] | None = None,
) -> Stitch:
    """Stitch ``cir.rooms`` and attach the on/off drift ablation (G-DRIFT)."""
    stitch = run_stitch(cir, loop_closure=cfg.loop_closure, diagnostics=diagnostics)
    stitch.ablation = run_ablation(cir)
    if stitch.unstitched and rooms_connected(cir.rooms):
        # Co-registered rooms that share walls are one connected plan; the flag
        # only survives when a room is geometrically isolated (I3 rule 4).
        stitch.unstitched = False
    return stitch


def ablation_transforms(cir: CIR) -> dict[str, dict[str, SE2]]:
    """Plan-frame room transforms for the loop-closure on/off passes (ablation SVG)."""
    return {
        "on": run_stitch(cir, loop_closure=True).room_transforms,
        "off": run_stitch(cir, loop_closure=False).room_transforms,
    }
