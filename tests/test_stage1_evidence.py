"""Stage-1 observed-evidence tests (plan 04i cleanup).

Stage 1 must be a pure, deterministic function of its input: same points + camera
-> byte-identical JSON. It is layered evidence (wall cells with per-cell support,
floor cells, camera free-space) and never fails.
"""

from __future__ import annotations

import json

import numpy as np

from scan2plan.config import Config
from scan2plan.geometry import observed_evidence, wall_cells_with_support
from scan2plan.geometry.planes import horizontal_planes


def _room_points(n: int = 40) -> np.ndarray:
    """A simple rectangular room cloud (floor + ceiling + 4 walls)."""
    xs = np.linspace(0.0, 4.0, n)
    zs = np.linspace(0.0, 3.0, n)
    fx, fz = np.meshgrid(xs, zs)
    floor = np.column_stack([fx.ravel(), np.zeros(fx.size), fz.ravel()])
    ceil = np.column_stack([fx.ravel(), np.full(fx.size, 2.5), fz.ravel()])
    ys = np.linspace(0.0, 2.5, 20)
    walls = []
    for xa, za, xb, zb in ((0, 0, 4, 0), (4, 0, 4, 3), (4, 3, 0, 3), (0, 3, 0, 0)):
        t = np.linspace(0.0, 1.0, n)
        for y in ys:
            walls.append(np.column_stack([xa + t * (xb - xa), np.full(n, y), za + t * (zb - za)]))
    return np.vstack([floor, ceil] + walls)


def _cam() -> np.ndarray:
    k = np.linspace(0, 2 * np.pi, 30)
    return np.stack([2 + np.cos(k), np.zeros_like(k), 1.5 + 0.5 * np.sin(k)], 1)


def test_observed_evidence_is_layered_not_a_polygon() -> None:
    pts = _room_points()
    s1 = observed_evidence(pts, _cam(), floor_y=0.0, ceil_y=2.5, cfg=Config())
    assert s1["name"] == "observed evidence"
    assert "polygon_xz" not in s1  # no hull/closed outline in stage 1
    assert set(s1["layers"]) == {"wall_cells", "floor_cells", "camera_free_space"}  # type: ignore[arg-type]
    wall = s1["layers"]["wall_cells"]  # type: ignore[index]
    assert wall and all("support" in c for c in wall)
    assert "camera_inside_fraction" in s1["statistics"]  # type: ignore[operator]


def test_observed_evidence_is_deterministic() -> None:
    """Same input -> byte-identical stage-1 JSON (no RNG, no hidden state)."""
    pts = _room_points()
    cam = _cam()
    a = observed_evidence(pts, cam, 0.0, 2.5, Config())
    b = observed_evidence(pts, cam, 0.0, 2.5, Config())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_observed_evidence_no_camera_does_not_fail() -> None:
    pts = _room_points()
    s1 = observed_evidence(pts, np.empty((0, 3)), 0.0, 2.5, Config())
    assert s1["statistics"]["camera_inside_fraction"] is None  # type: ignore[index]


def test_wall_cells_support_counts_monotone() -> None:
    pts = _room_points()
    cells, counts = wall_cells_with_support(pts, 0.0, 2.5, Config())
    assert cells.shape[0] == counts.shape[0] > 0
    assert counts.min() >= 1  # every kept cell is occupied in >= 1 height bin


def test_floor_plane_detected_for_evidence() -> None:
    pts = _room_points()
    planes = horizontal_planes(pts[:, 1])
    assert planes and abs(planes[0].height_m) < 0.05
