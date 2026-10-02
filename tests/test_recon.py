"""Tests for stage S2 LiDAR recon (plan 04b, task B-1)."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from scan2plan.config import Config
from scan2plan.ingest import ingest_capture
from scan2plan.recon import UnsupportedTierError, run_recon
from scan2plan.recon.lidar import reconstruct_lidar, voxel_downsample


def test_voxel_downsample_is_deterministic() -> None:
    pts = np.array([[0.0, 0.0, 0.0], [0.001, 0.0, 0.0], [0.02, 0.0, 0.0], [1.0, 1.0, 1.0]])
    out = voxel_downsample(pts, 0.01)
    assert out.shape == (3, 3)  # first two collapse into one 1 cm voxel
    assert np.array_equal(out, voxel_downsample(pts, 0.01))


def test_voxel_downsample_empty() -> None:
    assert voxel_downsample(np.empty((0, 3)), 0.01).shape == (0, 3)


def test_reconstruct_lidar_metric_points(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=3, shape=(16, 16))
    cir = ingest_capture(cap)
    points, quality = reconstruct_lidar(cap, cir.frames, Config(), stride=1, voxel_m=0.01)
    assert points.shape[1] == 3
    assert points.shape[0] > 0
    assert np.isfinite(points).all()
    assert quality.track_len == 3.0
    # depth = 2000 mm = 2 m along the forward axis (+Z, pinhole, per ADR-0002)
    assert np.all(points[:, 2] > 0)


def test_reconstruct_lidar_honours_confidence_filter(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=1, shape=(8, 8))
    # zero out the confidence so every point must be dropped
    import numpy as _np
    from PIL import Image

    Image.fromarray(_np.zeros((8, 8), dtype=_np.uint8)).save(cap / "confidence" / "000000.png")
    cir = ingest_capture(cap)
    points, _ = reconstruct_lidar(cap, cir.frames, Config(), stride=1, voxel_m=0.01)
    assert points.shape[0] == 0


def test_run_recon_writes_artifacts(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=3, shape=(16, 16))
    cir = ingest_capture(cap)
    out_dir = tmp_path / "out" / "cafebeef"
    recon = run_recon(cap, cir, Config(), out_dir)
    assert recon.points_ref is not None and (out_dir / recon.points_ref).is_file()
    assert recon.pose_graph_ref is not None and (out_dir / recon.pose_graph_ref).is_file()
    assert recon.scale_source == "lidar"
    assert recon.scale == 1.0


def test_run_recon_rejects_non_lidar(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path)
    shutil.rmtree(cap / "depth")
    shutil.rmtree(cap / "confidence")
    (cap / "photos").mkdir()  # now tier = photos
    cir = ingest_capture(cap)
    assert cir.session.tier == "photos"
    with pytest.raises(UnsupportedTierError):
        run_recon(cap, cir, Config(), tmp_path / "out")
