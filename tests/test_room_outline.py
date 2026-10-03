"""Tests for the three-stage room outline (plan 04i).

Covers the acceptance checks: self-test area, fridge run-length rejection, mirror
ghost rejection, unobserved wall handling, step snapping/merging, occluder
detection + widened intervals, and determinism.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scan2plan.config import Config
from scan2plan.geometry import wall_model as wm
from scan2plan.geometry.room_outline import (
    _length_half_width,
    _orthogonalize_uv,
    build_outline,
    detect_occluder_sides,
    wall_params_from_config,
)

P = wall_params_from_config(Config())


def test_selftest_area_matches_truth() -> None:
    pts, cam, fy, cy, (w, d) = wm.synthetic_room()
    res = wm.fit_room(pts, cam, fy, cy, params=P, n_boot=50, seed=1337)
    assert res["area_m2"]["value"] == pytest.approx(w * d, rel=0.05)  # 12.80


def test_fridge_rejected_by_run_length() -> None:
    # The synthetic has a 0.7 m tall fridge; the MIN_RUN length test must reject it
    # (if chosen it would shrink the width).
    pts, cam, fy, cy, (w, d) = wm.synthetic_room()
    res = wm.fit_room(pts, cam, fy, cy, params=P, n_boot=50, seed=1337)
    assert res["area_m2"]["value"] > 0.9 * w * d


def test_mirror_ghost_not_chosen() -> None:
    # The 2 m-behind mirror ghost must not be selected as a wall.
    pts, cam, fy, cy, (w, d) = wm.synthetic_room()
    res = wm.fit_room(pts, cam, fy, cy, params=P, n_boot=50, seed=1337)
    assert res["area_m2"]["value"] == pytest.approx(w * d, rel=0.06)


def test_longest_run_rejects_short_run() -> None:
    assert wm.longest_run(np.linspace(0.0, 3.0, 200)) == pytest.approx(3.0, abs=0.1)
    assert wm.longest_run(np.array([0.0, 0.5])) < P.min_run_m


def _three_walls() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    chunks = []

    def wall(p0: tuple[float, float], p1: tuple[float, float], n: int = 8000) -> None:
        t = rng.uniform(0, 1, n)
        x = p0[0] + (p1[0] - p0[0]) * t
        z = p0[1] + (p1[1] - p0[1]) * t
        y = rng.uniform(-1.4, 1.1, n)
        chunks.append(np.stack([x, y, z], 1))

    wall((0, 0), (4, 0))
    wall((4, 0), (4, 3))
    wall((0, 3), (0, 0))  # z=d wall omitted on purpose
    k = np.linspace(0, 2 * np.pi, 60)
    cam = np.stack([2 + np.cos(k), np.zeros_like(k), 1.5 + 0.5 * np.sin(k)], 1)
    return np.concatenate(chunks), cam


def test_unobserved_side_reported() -> None:
    pts, cam = _three_walls()
    res = wm.fit_room(pts, cam, -1.4, 1.1, params=P, n_boot=10, seed=1337)
    assert any(v is None for v in res["walls_uv"].values())  # type: ignore[union-attr]
    assert any("unobserved" in str(w) for w in res["warnings"])  # type: ignore[union-attr]


def test_orthogonalize_merges_short_step() -> None:
    lines_u = [0.0, 4.0]
    lines_v = [0.0, 3.0]
    # a 0.1 m step (v jumps 3.0 -> 3.1) must merge into its neighbour
    uv = np.array([[0, 0], [4, 0], [4, 3], [2, 3.1], [0, 3]], dtype=np.float64)
    out = _orthogonalize_uv(uv, lines_u, lines_v, 0.3)
    assert out.shape[0] == 4  # step removed -> rectangle


def test_orthogonalize_keeps_large_step() -> None:
    lines_u = [0.0, 4.0]
    lines_v = [0.0, 3.0]
    # a 1.5 m notch (concave L) must survive
    uv = np.array([[0, 0], [4, 0], [4, 1.5], [2, 1.5], [2, 3], [0, 3]], dtype=np.float64)
    out = _orthogonalize_uv(uv, lines_u, lines_v, 0.3)
    assert out.shape[0] == 6


def test_detect_occluder_flags_wardrobe() -> None:
    pts, cam, fy, cy, _ = wm.synthetic_room(wardrobe=True)
    res = wm.fit_room(pts, cam, fy, cy, params=P, n_boot=10, seed=1337)
    sides = detect_occluder_sides(res["uv"], res["walls_uv"], P, Config())  # type: ignore[arg-type]
    assert sides, "wardrobe face should be flagged as a suspected occluder"


def test_interval_widens_when_occluded() -> None:
    fit = {"pos_ci": {"u_min": (-0.01, 0.01)}, "width_m": {"value": 4.0, "ci": (-0.02, 0.02)}}
    cfg = Config()
    base = _length_half_width("u_min", 4.0, fit, cfg, "observed")
    wide = _length_half_width("u_min", 4.0, fit, cfg, "partially_occluded")
    assert wide == pytest.approx(base * cfg.outline.occluded_ci_scale, rel=0.2)
    assert wide > base


def test_interval_has_odometry_term() -> None:
    # zero bootstrap CI still yields a non-zero (odometry-driven) interval
    fit = {"pos_ci": {"u_min": (0.0, 0.0)}, "width_m": {"value": 4.0, "ci": (0.0, 0.0)}}
    half = _length_half_width("u_min", 4.0, fit, Config(), "observed")
    assert half == pytest.approx(Config().outline.odometry_ci_frac * 4.0, rel=0.2)


def test_build_outline_deterministic() -> None:
    pts, cam, fy, cy, _ = wm.synthetic_room()
    a = build_outline(pts, cam, tier="lidar", floor_y=fy, ceil_y=cy, cfg=Config())
    b = build_outline(pts, cam, tier="lidar", floor_y=fy, ceil_y=cy, cfg=Config())
    assert json.dumps(a.stage3, sort_keys=True, default=str) == json.dumps(
        b.stage3, sort_keys=True, default=str
    )
    assert json.dumps(a.stage2, sort_keys=True, default=str) == json.dumps(
        b.stage2, sort_keys=True, default=str
    )
