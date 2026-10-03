"""Stage-3 room tests (plan 04c/04h/04i): synthetic generator, then real invariants.

Deterministic: two runs of ``build_stage3`` on the same inputs must be byte-identical.
"""

from __future__ import annotations

import json
import math

import numpy as np

from scan2plan.config import Config
from scan2plan.geometry.rooms import (
    INFERRED_CLOSURE,
    OBSERVED,
    build_stage3,
    closure_cost,
    find_dangling_ends,
    plan_score,
    point_in_polygon,
    polygon_area,
)
from scan2plan.geometry.wall_complete import WallPiece


def _wall(axis: int, offset: float, a0: float, a1: float, prov: str = "observed") -> dict:
    """A stage-2 segment dict (uv frame) for a synthetic plan."""
    return {
        "axis": "u" if axis == 0 else "v",
        "offset_m": offset,
        "start_m": a0,
        "end_m": a1,
        "thickness_m": 0.0,
        "length": {"value": a1 - a0},
        "provenance": prov,
        "inferred": prov != "observed",
        "rule": "",
        "extension_m": 0.0,
        "ci_m": 0.0,
        "support": 40,
        "coverage": 1.0,
        "peak_strength": 1.0,
        "merged_from": 1,
        "endpoints_world": {"a": [a0, offset], "b": [a1, offset]},
    }


def _stage2(segments: list[dict], angle: float = 0.0) -> dict:
    return {
        "name": "wall segments",
        "manhattan_angle_deg": angle,
        "segments": segments,
        "graph": {"nodes": [], "edges": [], "counts": {}},
        "openings": [],
        "open_spaces": [],
        "unknown_gaps": [],
    }


def _stage1(wall_cells: list[dict], floor_cells: list[list[float]], cam: list[list[float]]) -> dict:
    return {
        "name": "observed evidence",
        "params": {"evidence_bin_m": 0.10, "cell_m": 0.02},
        "camera_xz": cam,
        "camera_start": cam[0] if cam else None,
        "camera_end": cam[-1] if cam else None,
        "layers": {
            "wall_cells": wall_cells,
            "floor_cells": floor_cells,
            "camera_free_space": [],
        },
        "layer_counts": {
            "wall_cells": len(wall_cells),
            "floor_cells": len(floor_cells),
            "camera_free_space": 0,
        },
        "statistics": {},
        "warnings": [],
    }


def _line_cells(x0: float, z0: float, x1: float, z1: float, support: int = 8) -> list[dict]:
    n = max(2, int(math.hypot(x1 - x0, z1 - z0) / 0.02))
    xs = np.linspace(x0, x1, n)
    zs = np.linspace(z0, z1, n)
    return [{"x": float(a), "z": float(b), "support": support} for a, b in zip(xs, zs, strict=True)]


def _rect_room(x0: float, z0: float, x1: float, z1: float) -> list[dict]:
    cells = []
    cells += _line_cells(x0, z0, x1, z0)
    cells += _line_cells(x1, z0, x1, z1)
    cells += _line_cells(x1, z1, x0, z1)
    cells += _line_cells(x0, z1, x0, z0)
    return cells


def _floor(x0: float, z0: float, x1: float, z1: float, step: float = 0.10) -> list[list[float]]:
    return [
        [float(a), float(b)]
        for a in np.arange(x0, x1 + 1e-9, step)
        for b in np.arange(z0, z1 + 1e-9, step)
    ]


def _cam(x0: float, z0: float, x1: float, z1: float, n: int = 12) -> list[list[float]]:
    return [
        [float(a), float(b)]
        for a, b in zip(np.linspace(x0, x1, n), np.linspace(z0, z1, n), strict=True)
    ]


def _single_rect_payload() -> tuple[dict, dict]:
    w, d = 4.0, 3.0
    segs = [
        _wall(0, 0.0, 0.0, d),
        _wall(0, w, 0.0, d),
        _wall(1, 0.0, 0.0, w),
        _wall(1, d, 0.0, w),
    ]
    s1 = _stage1(_rect_room(0, 0, w, d), _floor(0, 0, w, d), _cam(1.0, 1.0, 3.0, 2.0))
    return s1, _stage2(segs)


def _l_room_payload() -> tuple[dict, dict]:
    """An L-shaped room: union of a 4x3 block and a 2x3 wing (area 18)."""
    # boundary cells of the L (6 corners)
    poly = [(0, 0), (4, 0), (4, 3), (2, 3), (2, 6), (0, 6)]
    segs: list[dict] = []
    for k in range(len(poly)):
        (ax, az), (bx, bz) = poly[k], poly[(k + 1) % len(poly)]
        if ax == bx:
            segs.append(_wall(0, ax, min(az, bz), max(az, bz)))
        else:
            segs.append(_wall(1, az, min(ax, bx), max(ax, bx)))
    cells = []
    for k in range(len(poly)):
        (ax, az), (bx, bz) = poly[k], poly[(k + 1) % len(poly)]
        cells += _line_cells(ax, az, bx, bz)
    s1 = _stage1(cells, _floor(0, 0, 4, 3) + _floor(0, 3, 2, 6), _cam(1.0, 1.0, 1.0, 5.0))
    return s1, _stage2(segs)


def test_single_rect_room_area_and_walls() -> None:
    s1, s2 = _single_rect_payload()
    s3 = build_stage3(s1, s2, Config(), floor_y=0.0)
    assert s3["room_count"] == 1
    room = s3["rooms"][0]
    assert abs(room["area"]["value"] - 12.0) < 1.0
    assert room["area"]["ci_low"] <= room["area"]["value"] <= room["area"]["ci_high"]
    assert room["perimeter"]["observed_frac"] > 0.8  # mostly observed walls
    # four walls, each ~3-4 m
    assert len(room["wall_lengths"]) >= 4


def test_l_shaped_room_area() -> None:
    s1, s2 = _l_room_payload()
    s3 = build_stage3(s1, s2, Config(), floor_y=0.0)
    assert s3["room_count"] == 1
    room = s3["rooms"][0]
    assert abs(room["area"]["value"] - 18.0) < 3.0  # L-shape, not the 24 m2 bounding box
    assert len(room["polygon_uv"]) >= 6  # more than a rectangle


def test_deterministic_two_runs_byte_identical() -> None:
    s1, s2 = _l_room_payload()
    a = build_stage3(s1, s2, Config(), floor_y=0.0)
    b = build_stage3(s1, s2, Config(), floor_y=0.0)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_ceiling_unmeasured_with_prior_interval() -> None:
    s1, s2 = _single_rect_payload()
    s3 = build_stage3(s1, s2, Config(), floor_y=0.0)  # no cloud -> no ceiling cells
    ceil = s3["rooms"][0]["ceiling"]
    assert ceil["status"] == "unmeasured"
    assert ceil["provenance"] == "prior"
    assert ceil["ci_low"] == 2.4 and ceil["ci_high"] == 2.7
    assert ceil["value"] is not None


def test_no_room_assumption_of_rectangle_or_names() -> None:
    s1, s2 = _single_rect_payload()
    s3 = build_stage3(s1, s2, Config(), floor_y=0.0)
    flat = json.dumps(s3)
    assert "room_living" not in flat  # no names
    assert all(r["id"].startswith("room_") for r in s3["rooms"])


def test_polygon_area_shoelace() -> None:
    assert abs(polygon_area([(0, 0), (2, 0), (2, 3), (0, 3)]) - 6.0) < 1e-9


def test_point_in_polygon() -> None:
    sq = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    assert point_in_polygon(1.0, 1.0, sq)
    assert not point_in_polygon(3.0, 1.0, sq)


def test_closure_cost_forbids_camera_crossing() -> None:
    from scan2plan.geometry.rooms import RoomParams

    p = RoomParams(
        grid_m=0.02,
        evidence_bin_m=0.10,
        min_step_m=0.3,
        room_min_area_m2=0.5,
        closure_max_m=2.5,
        closure_wall_tol_m=0.05,
        closure_bonus_m=1.0,
        closure_floor_penalty=1.0,
        waist_min_m=0.6,
        waist_max_m=2.5,
        mc_samples=100,
        ceiling_min_above_floor_m=1.8,
        ceiling_bin_m=0.02,
        ceiling_prior_low_m=2.4,
        ceiling_prior_high_m=2.7,
        ci_base_m=0.03,
        ci_per_m=0.15,
        odometry_ci_frac=0.01,
        node_merge_m=0.10,
        seed=0,
    )
    cand = WallPiece(axis=1, offset=0.0, start=0.0, end=1.5)
    cam = np.array([[0.75, -1.0], [0.75, 1.0]])  # crosses v=0 over the span
    assert closure_cost(cand, np.empty((0, 2)), np.empty((0, 2)), cam, p) is None
    far = np.array([[5.0, 5.0], [6.0, 6.0]])
    assert closure_cost(cand, np.empty((0, 2)), np.empty((0, 2)), far, p) is not None


def test_closure_cost_prefers_supported_lines() -> None:
    from scan2plan.geometry.rooms import RoomParams

    p = RoomParams(
        grid_m=0.02,
        evidence_bin_m=0.10,
        min_step_m=0.3,
        room_min_area_m2=0.5,
        closure_max_m=2.5,
        closure_wall_tol_m=0.05,
        closure_bonus_m=1.0,
        closure_floor_penalty=1.0,
        waist_min_m=0.6,
        waist_max_m=2.5,
        mc_samples=100,
        ceiling_min_above_floor_m=1.8,
        ceiling_bin_m=0.02,
        ceiling_prior_low_m=2.4,
        ceiling_prior_high_m=2.7,
        ci_base_m=0.03,
        ci_per_m=0.15,
        odometry_ci_frac=0.01,
        node_merge_m=0.10,
        seed=0,
    )
    cand = WallPiece(axis=1, offset=0.0, start=0.0, end=1.0)
    supported = np.array([[0.0, t] for t in np.linspace(0, 1.0, 60)])
    empty = np.empty((0, 2))
    far = np.array([[9.0, 9.0]])
    c_sup = closure_cost(cand, supported, empty, far, p)
    c_bare = closure_cost(cand, empty, empty, far, p)
    assert c_sup is not None and c_bare is not None
    assert c_sup < c_bare  # a supported line is cheaper to accept


def test_find_dangling_ends_and_plan_score_types() -> None:
    walls = [
        WallPiece(axis=1, offset=0.0, start=0.0, end=1.0),
        WallPiece(axis=1, offset=0.0, start=3.0, end=4.0),
    ]
    ends = find_dangling_ends(walls)
    assert len(ends) == 4  # both ends of both walls are free
    assert plan_score([]) == 0.0
    assert INFERRED_CLOSURE == "inferred_closure" and OBSERVED == "observed"


def test_interval_coverage_on_synthetic_truth() -> None:
    """Truth ~12 m2: the reported area interval should contain it on ~all seeds (target 95%)."""
    w, d = 4.0, 3.0
    segs = [
        _wall(0, 0.0, 0.0, d),
        _wall(0, w, 0.0, d),
        _wall(1, 0.0, 0.0, w),
        _wall(1, d, 0.0, w),
    ]
    s1 = _stage1(_rect_room(0, 0, w, d), _floor(0, 0, w, d), _cam(1.0, 1.0, 3.0, 2.0))
    s2 = _stage2(segs)
    inside = 0
    trials = 20
    for seed in range(trials):
        cfg = Config()
        cfg.seed = seed
        cfg.outline.mc_samples = 40
        s3 = build_stage3(s1, s2, cfg, floor_y=0.0)
        area = s3["rooms"][0]["area"]
        if area["ci_low"] <= 12.0 <= area["ci_high"]:
            inside += 1
    share = inside / trials
    assert share >= 0.85  # near-nominal coverage on clean synthetic data
