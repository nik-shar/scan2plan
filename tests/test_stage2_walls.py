"""Stage-2 wall reconstruction tests (plan 04i).

Stage 2 must be a pure, deterministic function of the *frozen stage-1 artifact*:
same stage-1 JSON + config -> byte-identical wall JSON. It cleans the noisy wall
cells with the support gate and reconstructs Manhattan wall lines/segments; it
never produces a polygon, and it never fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from scan2plan.cli import app
from scan2plan.config import Config
from scan2plan.geometry import reconstruct_walls


def _stage1_payload(
    w: float = 4.0,
    d: float = 3.0,
    n: int = 60,
    *,
    wall_support: int = 6,
    ghost_support: int = 1,
    inset: bool = False,
) -> dict:
    """A synthetic stage-1 observed-evidence payload (4 walls + ghosts)."""
    wall: list[dict] = []
    for x in np.linspace(0.0, w, n):
        wall.append({"x": float(x), "z": 0.0, "support": wall_support})
        wall.append({"x": float(x), "z": float(d), "support": wall_support})
    for z in np.linspace(0.0, d, n):
        wall.append({"x": 0.0, "z": float(z), "support": wall_support})
        wall.append({"x": float(w), "z": float(z), "support": wall_support})
    if inset:
        # a 0.7 m run inset from the u_min wall -> must be rejected by min_run_m
        for z in np.linspace(2.0, 2.7, 15):
            wall.append({"x": 0.5, "z": float(z), "support": wall_support})
    for x in np.linspace(1.0, 2.0, 20):  # single-height-bin ghosts in the middle
        wall.append({"x": float(x), "z": 1.5, "support": ghost_support})
    floor = [[float(x), float(z)] for x in np.linspace(0.0, w, 20) for z in np.linspace(0.0, d, 20)]
    cam = [
        [float(w / 2 + 0.5 * np.cos(t)), float(d / 2 + 0.5 * np.sin(t))]
        for t in np.linspace(0.0, 2 * np.pi, 40)
    ]
    return {
        "name": "observed evidence",
        "params": {"cell_m": 0.02, "evidence_bin_m": 0.1, "min_height_bins": 4},
        "camera_xz": cam,
        "layers": {"wall_cells": wall, "floor_cells": floor, "camera_free_space": []},
        "layer_counts": {
            "wall_cells": len(wall),
            "floor_cells": len(floor),
            "camera_free_space": 0,
        },
        "statistics": {},
        "warnings": [],
    }


def _three_wall_payload() -> dict:
    """A payload with only 3 walls (the z=d side is missing) -> one unobserved."""
    w, d = 4.0, 3.0
    wall: list[dict] = []
    for z in np.linspace(0.0, 2.0, 100):  # side walls stop short of the missing wall
        wall.append({"x": 0.0, "z": float(z), "support": 6})
        wall.append({"x": float(w), "z": float(z), "support": 6})
    for x in np.linspace(0.0, w, 100):
        wall.append({"x": float(x), "z": 0.0, "support": 6})
    cam = [
        [float(w / 2 + 0.5 * np.cos(t)), float(d / 3 + 0.5 * np.sin(t))]
        for t in np.linspace(0.0, 2 * np.pi, 40)
    ]
    return {
        "name": "observed evidence",
        "camera_xz": cam,
        "layers": {"wall_cells": wall, "floor_cells": [], "camera_free_space": []},
        "layer_counts": {"wall_cells": len(wall), "floor_cells": 0, "camera_free_space": 0},
        "statistics": {},
        "warnings": [],
    }


def test_four_walls_recovered() -> None:
    s2 = reconstruct_walls(_stage1_payload(), Config())
    assert s2["name"] == "wall reconstruction"
    assert all(w["state"] == "observed" for w in s2["walls"])
    lengths = sorted(w["length_m"] for w in s2["walls"])
    assert lengths == pytest.approx([3.0, 3.0, 4.0, 4.0], abs=0.1)
    # axis-aligned synthetic room -> Manhattan angle ~ 0 (mod 90)
    angle = s2["manhattan_angle_deg"]
    assert min(angle, 90 - angle) == pytest.approx(0.0, abs=1.0)


def test_support_gate_drops_single_bin_cells() -> None:
    s2 = reconstruct_walls(_stage1_payload(), Config())
    cells = s2["cells"]
    assert cells["input"] == cells["kept"] + cells["dropped"]
    assert cells["dropped"] == 20  # exactly the ghosts
    assert cells["dropped_reasons"]["support_below_min_height_bins"] == cells["dropped"]


def test_inset_short_run_is_rejected() -> None:
    # the 0.7 m inset blob sits nearer the camera than the real wall; the run-length
    # test must reject it and keep the real u_min wall at u=0.
    s2 = reconstruct_walls(_stage1_payload(inset=True), Config())
    umin = next(w for w in s2["walls"] if w["side"] == "u_min")
    assert umin["state"] == "observed"
    assert umin["line_uv"]["pos"] == pytest.approx(0.0, abs=0.05)


def test_missing_wall_is_unobserved() -> None:
    s2 = reconstruct_walls(_three_wall_payload(), Config())
    states = {w["side"]: w["state"] for w in s2["walls"]}
    assert states["v_max"] == "unobserved"
    assert states["u_min"] == "observed"
    assert states["u_max"] == "observed"
    assert states["v_min"] == "observed"
    assert any("unobserved" in w for w in s2["warnings"])


def test_no_polygon_or_openings_in_stage2() -> None:
    s2 = reconstruct_walls(_stage1_payload(), Config())
    flat = json.dumps(s2)
    assert "polygon" not in flat  # walls are lines, not a closed outline
    assert "openings" not in flat
    assert "corners" not in flat


def test_deterministic_byte_identical() -> None:
    s1 = _stage1_payload()
    a = reconstruct_walls(s1, Config())
    b = reconstruct_walls(s1, Config())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_degenerate_no_wall_cells_does_not_fail() -> None:
    s1 = _stage1_payload()
    s1["layers"]["wall_cells"] = []
    s1["layer_counts"]["wall_cells"] = 0
    s2 = reconstruct_walls(s1, Config())
    assert all(w["state"] == "unobserved" for w in s2["walls"])
    assert s2["cells"]["kept"] == 0
    assert any("too few wall cells" in w for w in s2["warnings"])


def test_empty_camera_path_does_not_fail() -> None:
    s1 = _stage1_payload()
    s1["camera_xz"] = []
    s2 = reconstruct_walls(s1, Config())
    assert all(w["state"] == "unobserved" for w in s2["walls"])
    assert s2["camera_inside_walls_fraction"] is None


def test_cli_run_writes_stage2_walls(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=2, shape=(8, 8))
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(app, ["run", str(cap), "--out", str(out_dir)])
    assert result.exit_code == 0
    stage2 = out_dir / cap.name / "stage2_walls.json"
    assert stage2.is_file()
    assert (out_dir / cap.name / "stage2_walls.svg").is_file()
    data = json.loads(stage2.read_text())
    assert data["name"] == "wall reconstruction"
    assert len(data["walls"]) == 4
