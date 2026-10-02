"""Shared pytest fixtures (plans 02 section 1, task F-5 fixtures)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scan2plan.cir import (
    CIR,
    Damage,
    Extent,
    Measurement,
    Opening,
    Provenance,
    Room,
    Session,
    Surface,
    Tool,
)


def _measurement(
    id: str,
    kind: str,
    value: float,
    ci_low: float,
    ci_high: float,
    *,
    unit: str = "m",
    method: str = "plane_fit",
) -> Measurement:
    return Measurement(
        id=id,
        kind=kind,
        value=value,
        unit=unit,
        ci_low=ci_low,
        ci_high=ci_high,
        method=method,
        tier="lidar",
    )


@pytest.fixture
def valid_plan_dict() -> dict[str, Any]:
    """A complete, schema-valid plan.json built from the CIR models (stays consistent)."""
    tool = Tool(name="test-logger", version="0.0.0")
    room = Room(
        id="room_living",
        name="living",
        boundary=[[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]],
        ceiling_height=_measurement(
            "room_living.ceiling_height", "ceiling_height", 2.44, 2.43, 2.45
        ),
        floor_area=_measurement(
            "room_living.floor_area", "floor_area", 12.06, 11.8, 12.3, unit="m2", method="polygon"
        ),
    )
    surface = Surface(
        id="room_living_wall_1",
        room_id="room_living",
        type="wall",
        polygon=[[0.0, 0.0], [4.0, 0.0]],
    )
    opening = Opening(
        id="open_room_living_1",
        room_id="room_living",
        surface_id="room_living_wall_1",
        kind="door",
        width=_measurement("open_room_living_1.width", "opening_width", 0.812, 0.79, 0.83),
        height=_measurement("open_room_living_1.height", "opening_height", 2.031, 2.01, 2.05),
    )
    damage = Damage(
        id="dmg_9f31ab07",
        surface_id="room_living_wall_1",
        cls="water_stain",
        polygon=[[1.0, 0.5], [1.6, 0.5], [1.6, 0.9], [1.0, 0.9]],
        extent=Extent(area_m2=0.42),
        confidence=0.9,
    )
    cir = CIR(
        session=Session(
            id="cap_c00a170fe1",
            tier="lidar",
            device="iPhone 16 Pro",
            tool=tool,
            rooms_expected=1,
        ),
        rooms=[room],
        surfaces=[surface],
        openings=[opening],
        damages=[damage],
        provenance=Provenance(tier="lidar", tool=tool, git_sha="deadbeef", seed=1337),
    )
    return json.loads(cir.model_dump_json(exclude_none=True))
