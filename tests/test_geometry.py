"""Tests for stage S3 geometry (plan 04c, tasks G-1..G-5) on a synthetic room cloud."""

from __future__ import annotations

import numpy as np
import pytest

from scan2plan.geometry import estimate_orientation, extract_room
from scan2plan.geometry.planes import horizontal_planes


def make_room_cloud(
    length: float = 4.0,
    width: float = 3.0,
    height: float = 2.5,
    n: int = 60,
    door_x: tuple[float, float] | None = None,
) -> np.ndarray:
    """A clean axis-aligned rectangular room: floor grid, ceiling grid, 4 walls."""
    xs = np.linspace(0.0, length, n)
    zs = np.linspace(0.0, width, n)
    ys = np.linspace(0.0, height, 30)
    fx, fz = np.meshgrid(xs, zs)
    floor = np.column_stack([fx.ravel(), np.zeros(fx.size), fz.ravel()])
    ceil = np.column_stack([fx.ravel(), np.full(fx.size, height), fz.ravel()])

    edges = [
        (0.0, 0.0, length, 0.0),
        (length, 0.0, length, width),
        (length, width, 0.0, width),
        (0.0, width, 0.0, 0.0),
    ]
    walls = []
    for ei, (xa, za, xb, zb) in enumerate(edges):
        t = np.linspace(0.0, 1.0, n)
        xw = xa + t * (xb - xa)
        zw = za + t * (zb - za)
        for yy in ys:
            if door_x is not None and ei == 0:  # punch a door gap in the z=0 wall
                in_gap = (xw >= door_x[0]) & (xw <= door_x[1])
                keep = ~in_gap
                if not keep.any():
                    continue
                walls.append(np.column_stack([xw[keep], np.full(int(keep.sum()), yy), zw[keep]]))
            else:
                walls.append(np.column_stack([xw, np.full(n, yy), zw]))
    return np.vstack([floor, ceil] + walls)


def test_horizontal_planes_find_floor_and_ceiling() -> None:
    cloud = make_room_cloud(height=2.5)
    planes = horizontal_planes(cloud[:, 1])
    assert len(planes) == 2
    assert planes[0].height_m == pytest.approx(0.0, abs=0.02)
    assert planes[1].height_m == pytest.approx(2.5, abs=0.02)


def test_estimate_orientation_axis_aligned() -> None:
    cloud = make_room_cloud()
    theta = estimate_orientation(cloud[:, [0, 2]])
    assert abs(theta) < np.deg2rad(2.0)  # already axis-aligned


def test_extract_room_recovers_rotated_room() -> None:
    cloud = make_room_cloud()
    ang = np.deg2rad(35.0)
    c, s = np.cos(ang), np.sin(ang)
    rot = cloud.copy()
    xz = cloud[:, [0, 2]] @ np.array([[c, -s], [s, c]]).T
    rot[:, 0], rot[:, 2] = xz[:, 0], xz[:, 1]
    geom = extract_room(rot, tier="lidar")
    assert 10.0 < geom.room.floor_area.value < 14.0
    walls = [s for s in geom.surfaces if s.type == "wall"]
    lengths = sorted(
        float(np.hypot(*(np.array(s.polygon[1]) - np.array(s.polygon[0])))) for s in walls
    )
    assert lengths[0] == pytest.approx(3.0, abs=0.3)
    assert lengths[3] == pytest.approx(4.0, abs=0.3)


def test_extract_room_dimensions_and_surfaces() -> None:
    geom = extract_room(make_room_cloud(), tier="lidar")
    room = geom.room
    assert room.ceiling_height is not None
    assert room.ceiling_height.value == pytest.approx(2.5, abs=0.05)
    assert 10.0 < room.floor_area.value < 14.0
    walls = [s for s in geom.surfaces if s.type == "wall"]
    assert len(walls) == 4
    lengths = sorted(
        float(np.hypot(*(np.array(s.polygon[1]) - np.array(s.polygon[0])))) for s in walls
    )
    assert lengths[0] == pytest.approx(3.0, abs=0.3)
    assert lengths[3] == pytest.approx(4.0, abs=0.3)
    assert lengths[0] == pytest.approx(lengths[1], abs=0.05)  # opposite walls equal
    assert any(s.type == "floor" for s in geom.surfaces)
    assert any(s.type == "ceiling" for s in geom.surfaces)
    # no bare floats: every wall length + perimeter emitted as a Measurement
    kinds = {m.kind for m in geom.measures}
    assert "wall_length" in kinds and "perimeter" in kinds


def test_extract_room_closed_room_has_no_openings() -> None:
    geom = extract_room(make_room_cloud(), tier="lidar")
    assert geom.openings == []


def test_extract_room_detects_door_gap() -> None:
    geom = extract_room(make_room_cloud(door_x=(1.0, 1.9)), tier="lidar")
    assert len(geom.openings) >= 1
    widths = [o.width.value for o in geom.openings if o.width is not None]
    assert any(0.6 <= w <= 1.3 for w in widths)


def test_extract_room_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        extract_room(np.empty((0, 3)), tier="lidar")
