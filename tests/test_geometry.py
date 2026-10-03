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


#: Concave L-shaped footprint: main 4x3 minus the notch x in [2,4], z in [1.5,3].
#: CCW ring (0,0) (4,0) (4,1.5) (2,1.5) (2,3) (0,3) -> area 9 m2, six walls.
L_SHAPE_RING = np.array(
    [[0.0, 0.0], [4.0, 0.0], [4.0, 1.5], [2.0, 1.5], [2.0, 3.0], [0.0, 3.0]],
    dtype=np.float64,
)


def make_lshape_cloud(
    height: float = 2.5,
    n: int = 80,
    door_edge: int | None = None,
    door_span: tuple[float, float] = (0.35, 1.15),
) -> np.ndarray:
    """An L-shaped room (plan 04h): concave floor, ceiling, and one wall per edge.

    ``door_edge`` punches a door gap (metres along that edge) into one boundary
    wall so opening detection can be exercised on a concave footprint.
    """
    xs = np.linspace(0.0, 4.0, n)
    zs = np.linspace(0.0, 3.0, n)
    fx, fz = np.meshgrid(xs, zs)
    grid = np.column_stack([fx.ravel(), fz.ravel()])
    inside = ~((grid[:, 0] >= 2.0) & (grid[:, 1] >= 1.5))  # cut the notch
    grid = grid[inside]
    floor = np.column_stack([grid[:, 0], np.zeros(grid.shape[0]), grid[:, 1]])
    ceil = np.column_stack([grid[:, 0], np.full(grid.shape[0], height), grid[:, 1]])

    ys = np.linspace(0.0, height, 30)
    m = len(L_SHAPE_RING)
    walls = []
    for ei in range(m):
        a, b = L_SHAPE_RING[ei], L_SHAPE_RING[(ei + 1) % m]
        edge_len = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        t = np.linspace(0.0, 1.0, n)
        xw = a[0] + t * (b[0] - a[0])
        zw = a[1] + t * (b[1] - a[1])
        for yy in ys:
            keep = np.ones(n, dtype=bool)
            if door_edge is not None and ei == door_edge:
                along = t * edge_len
                keep = ~((along >= door_span[0]) & (along <= door_span[1]))
                if not keep.any():
                    continue
            cnt = int(keep.sum())
            walls.append(np.column_stack([xw[keep], np.full(cnt, yy), zw[keep]]))
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


# --- L-shaped (concave) footprint: plan 04h -----------------------------------


def test_extract_room_l_shape_area_and_walls() -> None:
    geom = extract_room(make_lshape_cloud(), tier="lidar")
    # 9 m2 L, not the 12 m2 bounding rectangle (mirrors the seed over-estimate bug)
    assert geom.room.floor_area.value == pytest.approx(9.0, rel=0.12)
    walls = [s for s in geom.surfaces if s.type == "wall"]
    assert len(walls) >= 6
    assert geom.room.ceiling_height is not None
    assert geom.room.ceiling_height.value == pytest.approx(2.5, abs=0.06)


def test_extract_room_l_shape_detects_door() -> None:
    geom = extract_room(make_lshape_cloud(door_edge=1), tier="lidar")
    assert len(geom.openings) >= 1
    widths = [o.width.value for o in geom.openings if o.width is not None]
    assert any(0.6 <= w <= 1.3 for w in widths)


def test_extract_room_l_shape_has_no_phantom_door() -> None:
    geom = extract_room(make_lshape_cloud(), tier="lidar")  # closed L
    assert geom.openings == []


def test_extract_room_is_deterministic() -> None:
    from dataclasses import asdict

    a = extract_room(make_lshape_cloud(door_edge=1), tier="lidar")
    b = extract_room(make_lshape_cloud(door_edge=1), tier="lidar")
    assert asdict(a) == asdict(b)


def test_extract_footprint_none_for_tiny_cloud() -> None:
    from scan2plan.geometry import extract_footprint

    assert extract_footprint(np.zeros((3, 2)), 0.0) is None
