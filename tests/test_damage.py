"""Tests for stages S5-S7: damage, concealed rules & scope (plan 04e)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scan2plan.cir import CIR, Plane, Provenance, Session, Surface
from scan2plan.config import Config
from scan2plan.damage.assess import assess
from scan2plan.damage.detect import detect_damages
from scan2plan.damage.evidence import SurfaceGrid, build_surface_evidence
from scan2plan.damage.rules import concealed_flags
from scan2plan.damage.scope import scope_items


def _grid(
    rgb: np.ndarray,
    count: np.ndarray,
    *,
    cell: float = 0.05,
    floor_y: float = 0.0,
) -> SurfaceGrid:
    nh, nu = rgb.shape[:2]
    return SurfaceGrid(
        surface_id="room_1_wall_1",
        room_id="room_1",
        a_xz=(0.0, 0.0),
        tangent=(1.0, 0.0),
        length_m=nu * cell,
        cell_m=cell,
        h0=0.2 + floor_y,
        h1=0.2 + nh * cell + floor_y,
        floor_y=floor_y,
        rgb_sum=rgb * count[..., None],
        count=count,
    )


def _uniform(nh: int, nu: int, rgb: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    return np.full((nh, nu, 3), rgb, dtype=float), np.full((nh, nu), 5, dtype=np.int64)


def test_detect_mold_and_water_stain() -> None:
    rgb, count = _uniform(40, 120, (200.0, 200.0, 200.0))
    rgb[5:12, 10:40] = (20.0, 20.0, 20.0)  # dark, desaturated -> mold
    rgb[20:28, 50:90] = (210.0, 180.0, 120.0)  # R-B=90 -> water_stain
    damages = detect_damages({"room_1_wall_1": _grid(rgb, count)}, Config())
    classes = {d.cls for d in damages}
    assert "mold" in classes
    assert "water_stain" in classes
    for d in damages:
        assert d.surface_id == "room_1_wall_1"
        assert d.extent.area_m2 is not None and d.extent.area_m2 > 0.0
        assert len(d.polygon) == 4


def test_detect_crack_is_elongated() -> None:
    rgb, count = _uniform(40, 120, (128.0, 128.0, 128.0))
    rgb[30, 20:100] = (200.0, 200.0, 200.0)  # bright line -> high gradient edges
    damages = detect_damages({"room_1_wall_1": _grid(rgb, count)}, Config())
    cracks = [d for d in damages if d.cls == "crack"]
    assert cracks, "an elongated bright line should read as a crack"
    for c in cracks:
        bbox = c.extent.bbox_m or [0.0, 0.0]
        assert max(bbox) / max(min(bbox), 1e-6) >= 2.5


def test_detect_is_deterministic() -> None:
    rgb, count = _uniform(30, 60, (200.0, 200.0, 200.0))
    rgb[5:10, 5:20] = (10.0, 10.0, 10.0)
    g = {"room_1_wall_1": _grid(rgb, count)}
    a = detect_damages(g, Config())
    b = detect_damages(g, Config())
    assert [d.model_dump() for d in a] == [d.model_dump() for d in b]


def test_detect_empty_grid_yields_nothing() -> None:
    rgb = np.full((10, 10, 3), np.nan)
    count = np.zeros((10, 10), dtype=np.int64)
    assert detect_damages({"room_1_wall_1": _grid(rgb, count)}, Config()) == []


def test_concealed_rules_fire_with_ids() -> None:
    rgb, count = _uniform(60, 120, (200.0, 200.0, 200.0))
    rgb[5:20, 10:60] = (20.0, 20.0, 20.0)  # big mold cluster -> bio + moist
    rgb[25:35, 20:100] = (210.0, 180.0, 120.0)  # big stain -> moist
    damages = detect_damages({"room_1_wall_1": _grid(rgb, count)}, Config())
    flags = concealed_flags(damages, Config())
    ids = {f.rule_id for f in flags}
    assert "R-CONCEAL-MOIST-01" in ids
    assert "R-CONCEAL-BIO-01" in ids
    for f in flags:
        assert f.surface_id == "room_1_wall_1"
        assert f.rule_text
        assert "area_m2" in f.inputs


def test_scope_items_units_and_ci() -> None:
    rgb, count = _uniform(40, 120, (128.0, 128.0, 128.0))
    rgb[30, 20:100] = (200.0, 200.0, 200.0)  # crack (metres)
    rgb[5:12, 10:40] = (210.0, 180.0, 120.0)  # stain (m2)
    damages = detect_damages({"room_1_wall_1": _grid(rgb, count)}, Config())
    items = scope_items(damages, Config(), tier="lidar")
    assert items
    units = {i.quantity.unit for i in items if i.quantity}
    assert units <= {"m", "m2"}
    for i in items:
        assert i.quantity is not None
        q = i.quantity
        assert q.ci_low <= q.value <= q.ci_high
        assert i.surface_id == "room_1_wall_1"


def test_build_surface_evidence_without_frames_warns() -> None:
    surface = Surface(
        id="room_1_wall_1",
        room_id="room_1",
        type="wall",
        plane=Plane(normal=[0.0, 0.0, 1.0], d=0.0),
        polygon=[[0.0, 0.0], [3.0, 0.0]],
    )
    cir = CIR(
        session=Session(id="cap_dmgtest", tier="lidar"),
        surfaces=[surface],
        provenance=Provenance(tier="lidar"),
    )
    grids, info = build_surface_evidence(cir, Path("/nonexistent"), Config(), Path("/tmp/dmg"))
    assert "room_1_wall_1" in grids
    assert grids["room_1_wall_1"].count.sum() == 0
    assert info["warnings"]


def test_assess_writes_damage_json(tmp_path: Path) -> None:
    surface = Surface(
        id="room_1_wall_1",
        room_id="room_1",
        type="wall",
        plane=Plane(normal=[0.0, 0.0, 1.0], d=0.0),
        polygon=[[0.0, 0.0], [3.0, 0.0]],
    )
    cir = CIR(
        session=Session(id="cap_dmgtest", tier="lidar"),
        surfaces=[surface],
        provenance=Provenance(tier="lidar"),
    )
    result = assess(cir, Path("/nonexistent"), Config(), tmp_path)
    assert result.damages == []
    report = json.loads((tmp_path / "damage.json").read_text())
    assert report["name"] == "damage"
    assert report["damage_count"] == 0
    assert "R-CONCEAL-MOIST-01" in report["rules"]
