"""Stage-2 multi-segment wall extraction tests (plan 04i).

Stage 2 is a pure, deterministic function of the *frozen stage-1 artifact*: the
same stage-1 JSON + config gives byte-identical wall JSON. It extracts **all** wall
segments (never a closing rectangle) and reports how much of the wall evidence they
explain.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from scan2plan.cli import app
from scan2plan.config import Config
from scan2plan.geometry import reconstruct_walls


def _line(
    cells: list[dict],
    *,
    x: float | None = None,
    z: float | None = None,
    lo: float,
    hi: float,
    n: int = 60,
    support: int = 6,
) -> None:
    """Add cells along a vertical (``x=const``) or horizontal (``z=const``) line."""
    for t in np.linspace(float(lo), float(hi), n):
        if x is not None:
            cells.append({"x": float(x), "z": float(t), "support": support})
        else:
            cells.append({"x": float(t), "z": float(z), "support": support})


def _finish(cells: list[dict], w: float, d: float, floor: list[list[float]] | None) -> dict:
    floor = (
        floor
        if floor is not None
        else [
            [float(x), float(z)] for x in np.linspace(0.0, w, 20) for z in np.linspace(0.0, d, 20)
        ]
    )
    cam = [
        [float(w / 2 + 0.8 * np.cos(t)), float(d / 2 + 0.8 * np.sin(t))]
        for t in np.linspace(0.0, 2 * np.pi, 40)
    ]
    return {
        "name": "observed evidence",
        "camera_xz": cam,
        "camera_start": cam[0],
        "camera_end": cam[-1],
        "layers": {"wall_cells": cells, "floor_cells": floor, "camera_free_space": []},
        "layer_counts": {
            "wall_cells": len(cells),
            "floor_cells": len(floor),
            "camera_free_space": 0,
        },
        "statistics": {},
        "warnings": [],
    }


def _payload(
    w: float = 4.0,
    d: float = 4.0,
    *,
    inner: bool = False,
    merge_face: bool = False,
    door: bool = False,
    ghosts: int = 0,
) -> dict:
    """An axis-aligned room (Manhattan angle 0) with optional inner wall/faces."""
    cells: list[dict] = []
    if door:
        _line(cells, x=0.0, lo=0.0, hi=1.6)
        _line(cells, x=0.0, lo=2.0, hi=d)
    else:
        _line(cells, x=0.0, lo=0.0, hi=d)
    _line(cells, x=w, lo=0.0, hi=d)
    _line(cells, z=0.0, lo=0.0, hi=w)
    _line(cells, z=d, lo=0.0, hi=w)
    if inner:
        _line(cells, z=2.5, lo=0.0, hi=2.0)  # partition, x in [0, 2]
    if merge_face:
        _line(cells, x=0.18, lo=0.2, hi=1.4)  # second face of the x=0 wall
    for i in range(ghosts):
        cells.append({"x": 1.0 + 0.05 * i, "z": 1.5, "support": 1})  # 1-height-bin noise
    return _finish(cells, w, d, None)


def _junction_payload() -> dict:
    """A u-line and a perpendicular v-line that are 0.25 m short of meeting."""
    cells: list[dict] = []
    _line(cells, x=0.0, lo=0.0, hi=3.75, n=150)  # u-line at x=0, ends 0.25 short of z=4
    _line(cells, z=4.0, lo=0.1, hi=4.0, n=150)  # v-line at z=4 (x starts at 0.1)
    return _finish(cells, 4.0, 4.0, [])


def _make(cells: list[dict], cam: list[list[float]], w: float = 10.0, d: float = 4.0) -> dict:
    """Assemble a payload with an explicit camera path (for completion tests)."""
    floor = [[float(x), float(z)] for x in np.linspace(0.0, w, 20) for z in np.linspace(0.0, d, 20)]
    return {
        "name": "observed evidence",
        "camera_xz": cam,
        "camera_start": cam[0],
        "camera_end": cam[-1],
        "layers": {"wall_cells": cells, "floor_cells": floor, "camera_free_space": []},
        "layer_counts": {
            "wall_cells": len(cells),
            "floor_cells": len(floor),
            "camera_free_space": 0,
        },
        "statistics": {},
        "warnings": [],
    }


def _gap_payload(a: float, b: float, *, cam_crosses: bool, wardrobe: bool = False) -> dict:
    """A z=0 wall broken into two runs with a gap ``[a, b]`` and a chosen camera path."""
    cells: list[dict] = []
    _line(cells, z=0.0, lo=0.0, hi=a, n=150)
    _line(cells, z=0.0, lo=b, hi=10.0, n=150)
    if wardrobe:  # dense low-support (unexplained) cells in front of the gap
        for i in range(200):
            cells.append({"x": float(a + (b - a) * (i % 20) / 20), "z": 0.3, "support": 1})
    if cam_crosses:
        cam = [[(a + b) / 2, -1.0], [(a + b) / 2, 1.0], [9.0, 1.5]]
    else:
        cam = [[1.0, 1.0], [8.0, 2.0], [9.0, 1.5]]
    return _make(cells, cam)


def test_outer_and_inner_walls_recovered() -> None:
    s2 = reconstruct_walls(_payload(inner=True), Config())
    segs = s2["segments"]
    assert s2["name"] == "wall segments"
    assert s2["wall_count"] == len(segs) >= 5
    # inner partition: a line at offset ~2.5 with length ~2.0 (either axis)
    inner = [s for s in segs if abs(s["offset_m"] - 2.5) < 0.1]
    assert inner and abs(inner[0]["length"]["value"] - 2.0) < 0.15
    # the four outer walls are long (~4 m)
    assert sum(1 for s in segs if s["length"]["value"] > 3.5) >= 4


def test_no_closing_rectangle() -> None:
    s2 = reconstruct_walls(_payload(), Config())
    assert "walls" not in s2  # not the old 4-wall rectangle record
    assert "segments" in s2
    flat = json.dumps(s2)
    assert "polygon" not in flat
    assert "camera_inside_walls_fraction" not in flat
    assert "corners" not in flat


def test_support_gate_drops_low_support_cells() -> None:
    s2 = reconstruct_walls(_payload(ghosts=20), Config())
    cells = s2["cells"]
    assert cells["dropped"] == 20
    assert cells["dropped_reasons"]["support_below_min_height_bins"] == 20
    assert cells["kept"] == cells["input"] - 20


def test_parallel_faces_merge_with_thickness() -> None:
    s2 = reconstruct_walls(_payload(merge_face=True), Config())
    merged = [s for s in s2["segments"] if s["merged_from"] >= 2 and s["thickness_m"] > 0.0]
    assert merged


def test_door_gap_splits_one_wall_into_two() -> None:
    s2 = reconstruct_walls(_payload(door=True), Config())
    at_zero = [s for s in s2["segments"] if abs(s["offset_m"]) < 0.05]
    assert len(at_zero) >= 2  # the 0.4 m doorway splits the x=0 wall into two runs


def test_junction_extension_is_inferred() -> None:
    s2 = reconstruct_walls(_junction_payload(), Config())
    segs = s2["segments"]
    ext = [s for s in segs if s["provenance"] == "inferred_extension"]
    assert ext  # the two nearly-meeting lines joined / extended
    seg = max(ext, key=lambda s: s["extension_m"])
    assert seg["extension_m"] > 0.2  # ~0.25 m extension to reach the other line
    assert seg["length"]["value"] > 3.9  # now spans the full ~4 m
    assert seg["ci_m"] > 0.0  # inferred interval grows with the assumed length


def test_short_gap_bridged_as_dropout() -> None:
    s2 = reconstruct_walls(_gap_payload(3.0, 3.2, cam_crosses=False), Config())
    assert s2["completion"]["bridged_dropout"] >= 1
    assert any(s["provenance"] == "inferred_dropout" for s in s2["segments"])


def test_camera_crossed_gap_is_opening() -> None:
    s2 = reconstruct_walls(_gap_payload(3.0, 4.5, cam_crosses=True), Config())
    assert len(s2["openings"]) >= 1
    assert s2["openings"][0]["rule"] == "camera_path_crosses_gap"
    # the door gap must NOT be bridged
    assert not any(
        s["provenance"] in ("inferred_occluded", "inferred_dropout") for s in s2["segments"]
    )


def test_furniture_gap_bridged_as_occluded() -> None:
    s2 = reconstruct_walls(_gap_payload(3.0, 4.5, cam_crosses=False, wardrobe=True), Config())
    assert s2["completion"]["bridged_occluded"] >= 1
    assert any(s["provenance"] == "inferred_occluded" for s in s2["segments"])


def test_stage2_exposes_completion_keys() -> None:
    s2 = reconstruct_walls(_payload(), Config())
    for key in ("segments", "openings", "unknown_gaps", "completion", "observed_count"):
        assert key in s2


def test_evidence_explained_full_for_clean_room() -> None:
    s2 = reconstruct_walls(_payload(), Config())
    ev = s2["evidence"]
    assert ev["cells_unexplained"] == 0
    assert ev["evidence_explained"] == 1.0
    assert ev["evidence_explained_kept"] == 1.0


def test_low_support_noise_is_unexplained() -> None:
    s2 = reconstruct_walls(_payload(ghosts=50), Config())
    ev = s2["evidence"]
    assert ev["cells_unexplained"] >= 50  # the ghosts are not near any segment
    assert ev["evidence_explained"] < 1.0


def test_deterministic_byte_identical() -> None:
    s1 = _payload(inner=True, ghosts=10)
    a = reconstruct_walls(s1, Config())
    b = reconstruct_walls(s1, Config())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_degenerate_no_wall_cells_does_not_fail() -> None:
    s1 = _payload()
    s1["layers"]["wall_cells"] = []
    s1["layer_counts"]["wall_cells"] = 0
    s2 = reconstruct_walls(s1, Config())
    assert s2["wall_count"] == 0
    assert s2["evidence"]["evidence_explained"] == 0.0
    assert any("too few wall cells" in w for w in s2["warnings"])


def test_cli_run_writes_segments_and_camera_markers(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=2, shape=(8, 8))
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(app, ["run", str(cap), "--out", str(out_dir)])
    assert result.exit_code == 0
    stage2 = out_dir / cap.name / "stage2_walls.json"
    assert stage2.is_file()
    assert (out_dir / cap.name / "stage2_walls.svg").is_file()
    data = json.loads(stage2.read_text())
    assert data["name"] == "wall segments"
    assert "segments" in data
    stage1 = json.loads((out_dir / cap.name / "stage1_observed.json").read_text())
    assert "camera_start" in stage1 and "camera_end" in stage1
