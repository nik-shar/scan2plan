"""Tests for the single-room SVG renderer (plan 04g, task O-3)."""

from __future__ import annotations

from pathlib import Path

from test_geometry import make_room_cloud

from scan2plan.geometry import extract_room
from scan2plan.render import render_room_svg


def test_render_room_svg_writes_valid_svg(tmp_path: Path) -> None:
    geom = extract_room(make_room_cloud(), tier="lidar")
    out = render_room_svg(geom, tmp_path / "plan.svg", title="cap_test")
    assert out.is_file()
    text = out.read_text()
    assert "<svg" in text and "</svg>" in text
    assert "<polygon" in text  # room boundary
    assert "m^2" in text  # floor-area label
    assert "ceiling height" in text  # ceiling label present for this room


def test_render_room_svg_no_ceiling(tmp_path: Path) -> None:
    import numpy as np

    cloud = make_room_cloud()
    cloud = cloud[cloud[:, 1] < 2.4]  # drop the ceiling slab
    geom = extract_room(cloud, tier="lidar")
    out = render_room_svg(geom, tmp_path / "plan.svg")
    text = out.read_text()
    assert "ceiling height" not in text
    assert np.isfinite(geom.room.floor_area.value)


def test_render_is_deterministic(tmp_path: Path) -> None:
    geom = extract_room(make_room_cloud(), tier="lidar")
    a = render_room_svg(geom, tmp_path / "a.svg").read_text()
    b = render_room_svg(geom, tmp_path / "b.svg").read_text()
    assert a == b
