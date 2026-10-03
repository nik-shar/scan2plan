"""Stage-3 invariant checks (plan 04i fix loop, section 1).

Each invariant must print its values and fail loudly (``ok=False``) on the exact
pathology it guards; skipped (``ok=None``) only when its subject does not exist.
"""

from __future__ import annotations

import numpy as np

from scan2plan.config import Config
from scan2plan.geometry.invariants import (
    check_stage3_invariants,
    inscribed_radius,
    invariants_failed,
)


def _room(rid: str, polygon: list[list[float]], *, ceil: dict | None = None) -> dict:
    return {
        "id": rid,
        "polygon_world": polygon,
        "area": {"value": 12.0, "ci_low": 11.0, "ci_high": 13.0},
        "ceiling": ceil or {"status": "unmeasured", "value": 2.55, "method": "prior"},
        "perimeter": {"observed_frac": 1.0},
        "wall_lengths": [],
    }


RECT_A = [[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]]
RECT_B = [[4.0, 0.0], [8.0, 0.0], [8.0, 3.0], [4.0, 3.0]]  # shares the x=4 edge
OVERLAP_B = [[3.5, 0.0], [7.5, 0.0], [7.5, 3.0], [3.5, 3.0]]  # 0.5 m into A
BOW_TIE = [[0.0, 0.0], [4.0, 0.0], [0.0, 3.0], [4.0, 3.0]]  # self-intersecting


def _stage1(free: list[list[float]], cam: list[list[float]]) -> dict:
    return {
        "layers": {"camera_free_space": free, "wall_cells": [], "floor_cells": []},
        "camera_xz": cam,
    }


def _stage2(segments: list[dict], nodes: list[dict]) -> dict:
    return {"segments": segments, "graph": {"nodes": nodes, "edges": []}, "open_spaces": []}


def _invariants(stage3: dict, stage1: dict | None = None, stage2: dict | None = None, **kw):
    return {
        i.name: i
        for i in check_stage3_invariants(
            stage1 or _stage1([], []),
            stage2 or _stage2([], []),
            stage3,
            Config(),
            **kw,
        )
    }


def test_inscribed_radius_is_half_the_shorter_rect_side() -> None:
    from shapely.geometry import Polygon

    assert abs(inscribed_radius(Polygon(RECT_A)) - 1.5) < 0.01


def test_no_overlap_passes_on_adjacent_rects() -> None:
    inv = _invariants({"rooms": [_room("room_1", RECT_A), _room("room_2", RECT_B)]})
    assert inv["no_overlap"].ok is True


def test_no_overlap_fails_on_overlap_and_bowtie_with_values() -> None:
    inv = _invariants({"rooms": [_room("room_1", RECT_A), _room("room_2", OVERLAP_B)]})
    assert inv["no_overlap"].ok is False
    assert inv["no_overlap"].values["total_overlap_m2"] > 1.0  # 0.5 m x 3 m slab
    bow = _invariants({"rooms": [_room("room_1", BOW_TIE)]})
    assert bow["no_overlap"].ok is False
    assert bow["no_overlap"].values["invalid_polygons"] == ["room_1"]


def test_min_room_fails_on_small_or_thin_room() -> None:
    tiny = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]  # 1 m2 < 2 m2
    thin = [[0.0, 0.0], [6.0, 0.0], [6.0, 0.4], [0.0, 0.4]]  # inradius 0.2 < 0.6
    inv = _invariants({"rooms": [_room("room_tiny", tiny), _room("room_thin", thin)]})
    assert inv["min_room"].ok is False
    names = [v["room"] for v in inv["min_room"].values["violations"]]
    assert names == ["room_tiny", "room_thin"]
    ok = _invariants({"rooms": [_room("room_1", RECT_A)]})
    assert ok["min_room"].ok is True


def test_coverage_and_camera_inside_with_opening_pass() -> None:
    stage3 = {
        "rooms": [_room("room_1", RECT_A)],
        "unobserved_enclosed": [],
        "openings": [{"id": "open_1", "axis": "u", "offset_m": 4.0, "start_m": 1.2, "end_m": 2.0}],
        "theta_rad": 0.0,
    }
    free = [[1.0, 1.0], [2.0, 1.5], [4.0, 1.6]]  # the last one sits in the opening
    cam = [[1.0, 1.0], [4.0, 1.6], [4.05, 1.6]]
    inv = _invariants(stage3, stage1=_stage1(free, cam))
    assert inv["coverage"].ok is True
    assert inv["camera_inside"].ok is True


def test_coverage_fails_when_cells_leak_outside() -> None:
    stage3 = {
        "rooms": [_room("room_1", RECT_A)],
        "unobserved_enclosed": [],
        "openings": [],
        "theta_rad": 0.0,
    }
    free = [[1.0, 1.0], [5.5, 1.0]]  # the second cell is outside every region
    inv = _invariants(stage3, stage1=_stage1(free, [[5.5, 1.0]]))
    assert inv["coverage"].ok is False
    assert inv["coverage"].values["share"] == 0.5
    assert inv["camera_inside"].ok is False


def test_render_clip_fails_when_span_extends_beyond_nodes() -> None:
    seg = {"axis": "u", "offset_m": 0.0, "start_m": 0.0, "end_m": 5.0}
    nodes = [{"id": "n1", "uv": [0.0, 0.5]}, {"id": "n2", "uv": [0.0, 3.0]}]
    inv = _invariants({"rooms": [_room("room_1", RECT_A)]}, stage2=_stage2([seg], nodes))
    assert inv["render_clip"].ok is False  # 0.5 + 2.0 m beyond the nodes
    assert inv["render_clip"].values["total_overshoot_m"] > 2.0
    ok_nodes = [{"id": "n1", "uv": [0.0, 0.0]}, {"id": "n2", "uv": [0.0, 5.0]}]
    ok = _invariants({"rooms": [_room("room_1", RECT_A)]}, stage2=_stage2([seg], ok_nodes))
    assert ok["render_clip"].ok is True


def test_ceiling_sanity_gates_measured_ceilings() -> None:
    xs, zs = np.meshgrid(np.linspace(0.2, 3.8, 30), np.linspace(0.2, 2.8, 24))
    pts = np.column_stack([xs.ravel(), np.full(xs.size, 2.5), zs.ravel()])
    good = _invariants(
        {
            "rooms": [
                _room(
                    "room_1",
                    RECT_A,
                    ceil={"status": "measured", "value": 2.5, "method": "plane_fit"},
                )
            ]
        },
        points_xyz=pts.astype(np.float64),
        floor_y=0.0,
    )
    assert good["ceiling_sanity"].ok is True
    few = pts[:20].copy()
    few[:, 1] = 2.0
    bad = _invariants(
        {
            "rooms": [
                _room(
                    "room_1",
                    RECT_A,
                    ceil={"status": "measured", "value": 2.0, "method": "plane_fit"},
                )
            ]
        },
        points_xyz=few.astype(np.float64),
        floor_y=0.0,
    )
    assert bad["ceiling_sanity"].ok is False
    assert bad["ceiling_sanity"].values["rooms"][0]["cells_ok"] is False
    assert bad["ceiling_sanity"].values["rooms"][0]["height_ok"] is False


def test_ceiling_spread_flags_inconsistent_ceiling() -> None:
    xs, zs = np.meshgrid(np.linspace(0.2, 3.8, 30), np.linspace(0.2, 2.8, 24))
    pts = np.column_stack([xs.ravel(), np.full(xs.size, 2.5), zs.ravel()]).astype(np.float64)
    stage3 = {
        "rooms": [
            _room(
                "room_1", RECT_A, ceil={"status": "measured", "value": 2.5, "method": "plane_fit"}
            ),
            _room(
                "room_2", RECT_B, ceil={"status": "measured", "value": 3.1, "method": "plane_fit"}
            ),
        ],
    }
    inv = _invariants(stage3, points_xyz=pts, floor_y=0.0)
    assert inv["ceiling_sanity"].ok is False
    assert inv["ceiling_sanity"].values["inconsistent_ceiling"] is True


def test_no_rooms_means_skips_never_fail() -> None:
    inv = _invariants({"rooms": []})
    assert all(i.ok is None for i in inv.values())
    assert invariants_failed(list(inv.values())) == []
