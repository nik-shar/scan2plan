"""Tests for stage S1 ingest (plan 04b, task B-1) on a synthetic I1 bundle."""

from __future__ import annotations

from pathlib import Path

import pytest

from scan2plan.ingest import ingest_capture, load_bundle
from scan2plan.ingest.bundle import BundleError, detect_tier


def test_detect_tier_lidar(make_lidar_bundle, tmp_path: Path) -> None:
    assert detect_tier(make_lidar_bundle(tmp_path)) == "lidar"


def test_load_bundle(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=4)
    bundle = load_bundle(cap)
    assert bundle.tier == "lidar"
    assert bundle.n_frames == 4
    assert bundle.capture_id == "cafebeef"
    assert bundle.camera_matrix.shape == (3, 3)
    assert bundle.camera_matrix[0, 0] == pytest.approx(100.0)
    assert len(bundle.depth_frames) == 4
    assert len(bundle.conf_frames) == 4


def test_load_bundle_missing_odometry_raises(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path)
    (cap / "odometry.csv").unlink()
    with pytest.raises(BundleError, match="odometry"):
        load_bundle(cap)


def test_load_bundle_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="not found"):
        load_bundle(tmp_path / "nope")


def test_ingest_capture_builds_cir(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=3)
    cir = ingest_capture(cap)
    assert cir.session.id == "cap_cafebeef"
    assert cir.session.tier == "lidar"
    assert len(cir.frames) == 3

    f0 = cir.frames[0]
    assert f0.idx == 0
    assert f0.depth_ref == "depth/000000.png"
    assert f0.conf_ref == "confidence/000000.png"
    assert f0.rgb_ref == "rgb.mp4"
    assert f0.pose is not None and len(f0.pose) == 16
    assert f0.K is not None and len(f0.K) == 9
    # identity quaternion + zero translation -> identity rotation row 0
    assert f0.pose[:4] == pytest.approx([1.0, 0.0, 0.0, 0.0])
    # frame 2 moved 1.0 m along +z (pose translation is column 3, row-major)
    assert cir.frames[2].pose[11] == pytest.approx(1.0)

    assert cir.provenance.tier == "lidar"
    assert cir.provenance.seed == 1337


def test_ingest_cir_validates_against_schema(make_lidar_bundle, tmp_path: Path) -> None:
    import json

    from scan2plan.cir.validate import validate_plan

    cir = ingest_capture(make_lidar_bundle(tmp_path))
    errors = validate_plan(json.loads(cir.model_dump_json(exclude_none=True)))
    assert errors == []
