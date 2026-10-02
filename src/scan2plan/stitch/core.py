"""Stage S4 driver: stitch rooms into one plan + drift ablation (plan 04d).

Pipeline (04d section 2): connector edges from matched openings (S-1) -> loop-
closure constraints from revisit detection (S-2, optional) -> SE(2) pose-graph
optimization (S-3) -> pairwise overlap check (S-4 gate ``overlap_ok``).

Drift policy (04d section 3 / G-DRIFT): initial placements come from odometry or
connectors and are treated as **initialisation only**; the optimizer always runs
when constraints exist. The ablation harness (``run_ablation``) emits on/off
footprints from this same code path - the only difference is whether closure
constraints are included.
"""

from __future__ import annotations

from typing import Any

from scan2plan.cir import CIR, SE2, Ablation, Footprint, LoopClosure, Stitch
from scan2plan.stitch.closures import detect_closures
from scan2plan.stitch.graph import match_connectors
from scan2plan.stitch.optimize import Constraint, _post_gap, optimize_pose_graph
from scan2plan.stitch.polygons import pairwise_overlaps, placed_polygons, union_area
from scan2plan.stitch.se2 import compose, relative

#: Two distinct rooms may touch along a wall; interior overlap above this fails
#: the no-overlap gate (G-PSTITCH).
OVERLAP_TOL_M2 = 0.02


def _connected(room_ids: list[str], links: list[tuple[str, str]], anchor: str) -> set[str]:
    """Rooms reachable from the anchor via constraint links (BFS)."""
    adj = {r: set() for r in room_ids}
    for a, b in links:
        adj[a].add(b)
        adj[b].add(a)
    seen: set[str] = set()
    stack = [anchor]
    while stack:
        r = stack.pop()
        if r in seen:
            continue
        seen.add(r)
        stack.extend(adj[r] - seen)
    return seen


def run_stitch(
    cir: CIR,
    *,
    loop_closure: bool = True,
    initial: dict[str, SE2] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> Stitch:
    """Stitch ``cir.rooms`` into the plan frame and return the CIR ``Stitch``.

    ``initial`` overrides per-room initial placements (default: identity, i.e.
    rooms already share a world frame - the LiDAR single-capture case). When
    ``diagnostics`` is a dict it is filled with ``footprint_m2``,
    ``closure_gap_m`` (mean post-optimization closure residual) and
    ``mean_residual`` for the ablation harness and reports.
    """
    rooms = {r.id: r for r in cir.rooms}
    ids = sorted(rooms)
    if not ids:
        if diagnostics is not None:
            diagnostics.update(footprint_m2=0.0, closure_gap_m=None, mean_residual=0.0)
        return Stitch()
    initials = {rid: SE2() for rid in ids}
    initials.update(initial or {})
    if len(ids) == 1:
        stitch = Stitch(
            room_transforms={ids[0]: initials[ids[0]]}, overlap_ok=True, unstitched=False
        )
        if diagnostics is not None:
            polys = placed_polygons(cir.rooms, stitch.room_transforms)
            diagnostics.update(
                footprint_m2=round(union_area(polys), 4), closure_gap_m=None, mean_residual=0.0
            )
        return stitch

    anchor = ids[0]
    edges = match_connectors(cir.rooms, cir.surfaces, cir.openings)
    linked = {(e.room_a, e.room_b) for e in edges} | {(e.room_b, e.room_a) for e in edges}
    placed = _connected(ids, [(e.room_a, e.room_b) for e in edges], anchor)

    closures: list[LoopClosure] = []
    closure_constraints: list[Constraint] = []
    if loop_closure:
        polys0 = placed_polygons(cir.rooms, initials)
        for m in detect_closures(polys0, eligible=placed):
            if (m.room_a, m.room_b) in linked:
                continue
            # Re-express the plan-frame correction as an a->b relative constraint:
            # T_ab = T_wb^-1 . (corr . T_wa) - room a's corrected placement seen
            # from room b's frame.
            meas = relative(initials[m.room_b], compose(m.correction, initials[m.room_a]))
            closure_constraints.append(Constraint(m.room_a, m.room_b, meas, m.weight))
            closures.append(LoopClosure(rooms=[m.room_a, m.room_b], gap_m=m.gap_m))

    constraints = [
        Constraint(e.room_a, e.room_b, e.transform, e.weight or 1.0) for e in edges
    ] + closure_constraints
    # Normalise weights so the strongest constraint has weight 1.
    if constraints:
        w_max = max(c.weight for c in constraints)
        constraints = [
            Constraint(c.room_a, c.room_b, c.meas, c.weight / w_max) for c in constraints
        ]

    result = optimize_pose_graph(ids, initials, constraints, anchor=anchor)
    transforms = result.transforms

    # Overlap gate (04d section 2.6): closure-linked pairs are revisits of the
    # same physical space, not adjacency errors, so they are excluded.
    revisited = {(c.room_a, c.room_b) for c in closure_constraints} | {
        (c.room_b, c.room_a) for c in closure_constraints
    }
    polys = placed_polygons(cir.rooms, transforms)
    bad_overlaps = {
        pair: area
        for pair, area in pairwise_overlaps(polys).items()
        if area > OVERLAP_TOL_M2 and pair not in revisited
    }
    overlap_ok = not bad_overlaps

    all_links = [(e.room_a, e.room_b) for e in edges] + [
        (c.room_a, c.room_b) for c in closure_constraints
    ]
    # I3 rule 4: a multi-room plan must be demonstrably stitched.
    unstitched = len(_connected(ids, all_links, anchor)) < len(ids)

    post_gaps = [_post_gap(c, transforms) for c in closure_constraints]
    if diagnostics is not None:
        diagnostics.update(
            footprint_m2=round(union_area(polys), 4),
            closure_gap_m=(round(sum(post_gaps) / len(post_gaps), 4) if post_gaps else None),
            mean_residual=round(result.mean_residual, 6),
        )

    return Stitch(
        room_transforms=transforms,
        edges=edges,
        closures=closures,
        overlap_ok=overlap_ok,
        unstitched=unstitched,
    )


def run_ablation(
    cir: CIR,
    *,
    initial: dict[str, SE2] | None = None,
) -> Ablation:
    """G-DRIFT ablation (04d section 4): on/off footprints, same code path.

    The only difference between the two runs is whether loop-closure constraints
    enter the pose graph; both footprints are union areas of the stitched room
    polygons and ``closure_gap_m`` is the mean post-optimization closure residual.
    """
    diag_on: dict[str, Any] = {}
    diag_off: dict[str, Any] = {}
    run_stitch(cir, loop_closure=True, initial=initial, diagnostics=diag_on)
    run_stitch(cir, loop_closure=False, initial=initial, diagnostics=diag_off)
    return Ablation(
        loop_closure_on=Footprint(
            footprint_m2=diag_on["footprint_m2"], closure_gap_m=diag_on["closure_gap_m"]
        ),
        off=Footprint(
            footprint_m2=diag_off["footprint_m2"], closure_gap_m=diag_off["closure_gap_m"]
        ),
    )
