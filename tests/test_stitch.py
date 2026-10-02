"""Tests for stage S4 stitching + drift ablation (plan 04d, tasks S-1..S-5).

Fixtures are synthetic two-room layouts with known relative transforms; the
multi-room benchmark capture (BM-1, plan 08) is still missing, so the real-data
path is covered by the single-room CLI tests in test_cli.py.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from scan2plan.cir import (
    CIR,
    SE2,
    Measurement,
    Opening,
    Plane,
    Provenance,
    Room,
    Session,
    Surface,
)
from scan2plan.cir.validate import validate_plan
from scan2plan.stitch import (
    Constraint,
    detect_closures,
    icp_correction,
    match_connectors,
    optimize_pose_graph,
    run_ablation,
    run_stitch,
)
from scan2plan.stitch.polygons import boundary_points, room_polygon
from scan2plan.stitch.se2 import apply, compose, inverse, relative, wrap_angle


def _measurement(id: str, value: float, hw: float = 0.02) -> Measurement:
    return Measurement(
        id=id,
        kind="opening_width",
        value=value,
        unit="m",
        ci_low=value - hw,
        ci_high=value + hw,
        method="wall_gap",
        tier="lidar",
    )


def make_room(
    room_id: str,
    *,
    size: tuple[float, float] = (4.0, 3.0),
    door: tuple[int, float] | None = None,
) -> tuple[Room, list[Surface], list[Opening]]:
    """Axis-aligned rectangular room at its local origin with 4 wall surfaces.

    Walls: 0 = bottom (normal -y), 1 = right (+x), 2 = top (+y), 3 = left (-x).
    ``door`` = (wall_index, width) adds a connector opening on that wall.
    """
    length, width = size
    corners = [(0.0, 0.0), (length, 0.0), (length, width), (0.0, width)]
    normals = [(0.0, -1.0), (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0)]
    room = Room(id=room_id, boundary=[[x, y] for x, y in corners])
    surfaces: list[Surface] = []
    openings: list[Opening] = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        nx, ny = normals[i]
        d = -(nx * a[0] + ny * a[1])
        sid = f"{room_id}_wall_{i + 1}"
        surfaces.append(
            Surface(
                id=sid,
                room_id=room_id,
                type="wall",
                plane=Plane(normal=[nx, 0.0, ny], d=d),
                polygon=[[a[0], a[1]], [b[0], b[1]]],
            )
        )
    if door is not None:
        wall_idx, door_w = door
        openings.append(
            Opening(
                id=f"open_{room_id}_1",
                room_id=room_id,
                surface_id=f"{room_id}_wall_{wall_idx + 1}",
                kind="door",
                width=_measurement(f"open_{room_id}_1.width", door_w),
                detection_confidence=0.9,
            )
        )
    return room, surfaces, openings


def make_cir(*parts: tuple[Room, list[Surface], list[Opening]]) -> CIR:
    return CIR(
        session=Session(id="cap_stitchtest", tier="lidar"),
        rooms=[p[0] for p in parts],
        surfaces=[s for p in parts for s in p[1]],
        openings=[o for p in parts for o in p[2]],
        provenance=Provenance(tier="lidar"),
    )


# --- SE(2) primitives --------------------------------------------------------


def test_se2_compose_inverse_roundtrip() -> None:
    a = SE2(x=1.2, y=-0.4, theta=0.7)
    b = SE2(x=-2.0, y=3.1, theta=-1.9)
    ident = compose(inverse(a), a)
    p = apply(compose(a, b), 0.3, -1.1)
    q = apply(a, *apply(b, 0.3, -1.1))
    assert ident.x == pytest.approx(0.0, abs=1e-12)
    assert ident.y == pytest.approx(0.0, abs=1e-12)
    assert ident.theta == pytest.approx(0.0, abs=1e-12)
    assert p == pytest.approx(q, abs=1e-12)


def test_wrap_angle_bounds() -> None:
    assert wrap_angle(3 * math.pi) == pytest.approx(-math.pi)
    assert wrap_angle(0.3) == pytest.approx(0.3)


# --- S-1 connector matching ----------------------------------------------------


def test_connector_matching_links_rooms_via_door() -> None:
    # Room B's true placement: to the right of A, sharing wall x=4 (T_wb = (4,0,0)).
    cir = make_cir(
        make_room("room_a", size=(4.0, 3.0), door=(1, 0.90)),  # door on right wall
        make_room("room_b", size=(3.5, 3.0), door=(3, 0.88)),  # door on left wall
    )
    edges = match_connectors(cir.rooms, cir.surfaces, cir.openings)
    assert len(edges) == 1
    assert {edges[0].room_a, edges[0].room_b} == {"room_a", "room_b"}
    assert edges[0].kind == "connector"


def test_connector_matching_rejects_width_mismatch() -> None:
    cir = make_cir(
        make_room("room_a", door=(1, 0.90)),
        make_room("room_b", door=(3, 1.40)),  # too different to be the same door
    )
    assert match_connectors(cir.rooms, cir.surfaces, cir.openings) == []


def test_connector_matching_ignores_windows() -> None:
    room_a, walls_a, openings_a = make_room("room_a", door=(1, 0.9))
    room_b, walls_b, openings_b = make_room("room_b", door=(3, 0.9))
    for o in openings_a + openings_b:
        o.kind = "window"  # windows never connect rooms
    cir = make_cir((room_a, walls_a, openings_a), (room_b, walls_b, openings_b))
    assert match_connectors(cir.rooms, cir.surfaces, cir.openings) == []


# --- S-3 pose-graph optimization -----------------------------------------------


def test_pose_graph_recovers_known_transforms() -> None:
    truth = {
        "room_a": SE2(x=0.0, y=0.0, theta=0.0),
        "room_b": SE2(x=4.0, y=0.2, theta=0.05),
        "room_c": SE2(x=4.1, y=3.4, theta=-0.03),
    }
    ids = sorted(truth)
    # Exact relative measurements a->b: T_ab = T_wb^-1 . T_wa
    constraints = [
        Constraint(a, b, relative(truth[b], truth[a]), 1.0)
        for a, b in (("room_a", "room_b"), ("room_b", "room_c"))
    ]
    # The anchor is held at its initial value (the graph is gauge-free), so only
    # the non-anchor initials are drifted.
    drifted = dict(truth)
    for rid in ("room_b", "room_c"):
        t = truth[rid]
        drifted[rid] = SE2(x=t.x + 0.15, y=t.y - 0.1, theta=t.theta + 0.04)
    result = optimize_pose_graph(ids, drifted, constraints, anchor="room_a")
    assert result.n_constraints == 2
    for rid in ids:
        got = result.transforms[rid]
        assert got.x == pytest.approx(truth[rid].x, abs=1e-6)
        assert got.y == pytest.approx(truth[rid].y, abs=1e-6)
        assert got.theta == pytest.approx(truth[rid].theta, abs=1e-6)


def test_pose_graph_unconstrained_rooms_keep_initial() -> None:
    initial = {"room_a": SE2(), "room_b": SE2(x=9.0, y=8.0, theta=0.2)}
    result = optimize_pose_graph(["room_a", "room_b"], initial, [], anchor="room_a")
    assert result.transforms["room_b"].x == pytest.approx(9.0)


# --- S-2 loop-closure detection --------------------------------------------------


def test_icp_correction_is_deterministic_and_recovers_offset() -> None:
    base = room_polygon(Room(id="r", boundary=[[0, 0], [4, 0], [4, 3], [0, 3]]))
    moved = room_polygon(
        Room(id="r", boundary=[[0, 0], [4, 0], [4, 3], [0, 3]]), SE2(x=0.15, y=0.1)
    )
    src, dst = boundary_points(moved), boundary_points(base)
    corr1, _ = icp_correction(src, dst)
    corr2, _ = icp_correction(src, dst)
    assert corr1 == corr2  # deterministic
    assert corr1.x == pytest.approx(-0.15, abs=0.02)
    assert corr1.y == pytest.approx(-0.1, abs=0.02)
    assert abs(corr1.theta) < 0.02


def test_detect_closures_flags_overlapping_revisit_only() -> None:
    base = Room(id="room_a", boundary=[[0, 0], [4, 0], [4, 3], [0, 3]])
    revisit = Room(id="room_b", boundary=[[0, 0], [4, 0], [4, 3], [0, 3]])
    far = Room(id="room_c", boundary=[[20, 20], [24, 20], [24, 23], [20, 23]])
    polys = {
        "room_a": room_polygon(base),
        "room_b": room_polygon(revisit, SE2(x=0.2, y=0.1)),  # same room, drifted
        "room_c": room_polygon(far),  # distinct, disjoint
    }
    matches = detect_closures(polys)
    assert [(m.room_a, m.room_b) for m in matches] == [("room_a", "room_b")]
    assert matches[0].gap_m == pytest.approx(math.hypot(0.2, 0.1), abs=0.05)


def test_detect_closures_respects_eligibility() -> None:
    polys = {
        "room_a": room_polygon(Room(id="room_a", boundary=[[0, 0], [4, 0], [4, 3], [0, 3]])),
        "room_b": room_polygon(
            Room(id="room_b", boundary=[[0, 0], [4, 0], [4, 3], [0, 3]]), SE2(x=0.2)
        ),
    }
    # Neither room in the anchor-connected component -> no closure (photo-tier guard).
    assert detect_closures(polys, eligible=set()) == []


# --- run_stitch / run_ablation (S-4, S-5) ----------------------------------------


def test_single_room_stitch_is_trivial() -> None:
    cir = make_cir(make_room("room_0"))
    stitch = run_stitch(cir)
    assert stitch.overlap_ok is True
    assert stitch.unstitched is False
    assert stitch.room_transforms["room_0"] == SE2()


def test_run_stitch_places_room_via_connector() -> None:
    cir = make_cir(
        make_room("room_a", size=(4.0, 3.0), door=(1, 0.90)),
        make_room("room_b", size=(3.5, 3.0), door=(3, 0.88)),
    )
    stitch = run_stitch(cir)  # both rooms at local origin; anchor = room_a
    tb = stitch.room_transforms["room_b"]
    assert tb.x == pytest.approx(4.0, abs=0.05)
    assert tb.y == pytest.approx(0.0, abs=0.05)
    assert abs(tb.theta) < 0.02
    assert stitch.overlap_ok is True
    assert stitch.unstitched is False
    # the stitched plan still validates against I3
    cir.stitch = stitch
    assert validate_plan(json.loads(cir.model_dump_json(exclude_none=True))) == []


def test_run_stitch_flags_unstitched_disconnected_rooms() -> None:
    room_b, walls_b, _ = make_room("room_b")
    room_b.boundary = [[20, 20], [24, 20], [24, 23], [20, 23]]
    cir = make_cir(make_room("room_a"), (room_b, walls_b, []))
    stitch = run_stitch(cir)
    assert stitch.unstitched is True  # I3 rule 4: not demonstrably stitched
    assert stitch.overlap_ok is True


def test_loop_closure_corrects_injected_drift() -> None:
    # Same physical room captured twice (revisit); room_b's initial placement is
    # drifted. Only loop closure can correct it (no connectors).
    cir = make_cir(
        make_room("room_a", size=(4.0, 3.0)),
        make_room("room_b", size=(4.0, 3.0)),
    )
    drift = SE2(x=0.15, y=0.10, theta=0.03)
    initial = {"room_a": SE2(), "room_b": drift}

    on = run_stitch(cir, loop_closure=True, initial=initial)
    assert len(on.closures) == 1
    assert on.closures[0].gap_m == pytest.approx(math.hypot(0.15, 0.10), abs=0.05)
    tb = on.room_transforms["room_b"]
    assert tb.x == pytest.approx(0.0, abs=0.03)
    assert tb.y == pytest.approx(0.0, abs=0.03)
    assert on.unstitched is False

    off = run_stitch(cir, loop_closure=False, initial=initial)
    assert off.closures == []
    assert off.room_transforms["room_b"] == drift  # unconstrained: drift stands
    assert off.unstitched is True  # no inter-room constraint -> not demonstrably stitched


def test_ablation_same_path_on_off_differ() -> None:
    cir = make_cir(
        make_room("room_a", size=(4.0, 3.0)),
        make_room("room_b", size=(4.0, 3.0)),
    )
    initial = {"room_a": SE2(), "room_b": SE2(x=0.15, y=0.10, theta=0.03)}
    ab = run_ablation(cir, initial=initial)
    assert ab.loop_closure_on is not None and ab.off is not None
    # With closure the two revisits align (union ~= one room); without, the
    # drifted union is strictly larger.
    assert ab.loop_closure_on.footprint_m2 == pytest.approx(12.0, abs=0.2)
    assert ab.off.footprint_m2 > ab.loop_closure_on.footprint_m2 + 0.1
    assert ab.loop_closure_on.closure_gap_m is not None
    assert ab.loop_closure_on.closure_gap_m < 0.02
    assert ab.off.closure_gap_m is None  # closures never ran in the off pass


def test_run_stitch_empty_cir() -> None:
    cir = CIR(session=Session(id="cap_empty000", tier="lidar"), provenance=Provenance(tier="lidar"))
    stitch = run_stitch(cir)
    assert stitch.room_transforms == {}
    ab = run_ablation(cir)
    assert ab.loop_closure_on is not None
    assert ab.loop_closure_on.footprint_m2 == 0.0


def test_stitch_is_deterministic() -> None:
    cir = make_cir(
        make_room("room_a", size=(4.0, 3.0)),
        make_room("room_b", size=(4.0, 3.0)),
    )
    initial = {"room_a": SE2(), "room_b": SE2(x=0.15, y=0.10, theta=0.03)}
    a = run_stitch(cir, loop_closure=True, initial=initial)
    b = run_stitch(cir, loop_closure=True, initial=initial)
    assert a.model_dump_json() == b.model_dump_json()
    assert np.isfinite(a.room_transforms["room_b"].x)
