"""Tests for the CLI-facing stitch wiring (plan 04d S-4/S-5)."""

from __future__ import annotations

from scan2plan.cir import CIR, Provenance, Room, Session
from scan2plan.config import Config
from scan2plan.stitch.wire import ablation_transforms, rooms_connected, stitch_plan


def _room(rid: str, x0: float, y0: float, w: float = 4.0, h: float = 3.0) -> Room:
    return Room(
        id=rid,
        boundary=[[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]],
    )


def _cir(*rooms: Room) -> CIR:
    return CIR(
        session=Session(id="cap_wiretest", tier="lidar"),
        rooms=list(rooms),
        provenance=Provenance(tier="lidar"),
    )


def test_rooms_connected_via_shared_wall() -> None:
    assert rooms_connected([_room("room_1", 0.0, 0.0), _room("room_2", 4.0, 0.0)]) is True


def test_rooms_not_connected_when_isolated() -> None:
    assert rooms_connected([_room("room_1", 0.0, 0.0), _room("room_2", 20.0, 20.0)]) is False


def test_single_room_is_connected() -> None:
    assert rooms_connected([_room("room_1", 0.0, 0.0)]) is True
    assert rooms_connected([]) is True


def test_stitch_plan_clears_false_unstitched_for_connected_rooms() -> None:
    cir = _cir(_room("room_1", 0.0, 0.0), _room("room_2", 4.0, 0.0))
    stitch = stitch_plan(cir, Config())
    assert stitch.unstitched is False  # co-registered rooms sharing a wall
    assert stitch.overlap_ok is True
    assert stitch.ablation is not None
    assert stitch.ablation.loop_closure_on is not None
    assert stitch.ablation.off is not None


def test_stitch_plan_keeps_unstitched_for_isolated_room() -> None:
    cir = _cir(_room("room_1", 0.0, 0.0), _room("room_2", 20.0, 20.0))
    stitch = stitch_plan(cir, Config())
    assert stitch.unstitched is True


def test_ablation_transforms_has_on_and_off() -> None:
    cir = _cir(_room("room_1", 0.0, 0.0), _room("room_2", 4.0, 0.0))
    tf = ablation_transforms(cir)
    assert set(tf) == {"on", "off"}
    assert set(tf["on"]) == {"room_1", "room_2"}
