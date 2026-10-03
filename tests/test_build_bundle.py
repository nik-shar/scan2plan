"""Capture tooling: build a conformant I1 bundle from a raw LiDAR-logger export (plan 03)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scan2plan.ingest.build import BundleBuildError, build_bundle
from scan2plan.ingest.bundle import DEPTH_SHAPE, load_bundle

K = np.array([[1599.7, 0.0, 955.5], [0.0, 1599.7, 717.8], [0.0, 0.0, 1.0]])


def _raw_export(
    root: Path,
    *,
    frames: int = 3,
    depth_dir: str = "depth",
    depth_value: int = 2000,
    confidence: bool = False,
    camera_matrix: bool = True,
    intrinsics_in_odometry: bool = True,
    shape: tuple[int, int] = DEPTH_SHAPE,
) -> Path:
    """A minimal raw logger export (the shape a stock LiDAR app hands over)."""
    (root / depth_dir).mkdir(parents=True, exist_ok=True)
    if confidence:
        (root / "confidence").mkdir(parents=True, exist_ok=True)
    if camera_matrix:
        np.savetxt(root / "camera_matrix.csv", K, delimiter=",")
    cols = "timestamp, frame, x, y, z, qx, qy, qz, qw"
    if intrinsics_in_odometry:
        cols += ", fx, fy, cx, cy"
    with (root / "odometry.csv").open("w") as fh:
        fh.write(cols + "\n")
        for i in range(frames):
            row = f"{0.1 * i}, {i:06d}, 0.0, 0.0, {0.2 * i}, 0.0, 0.0, 0.0, 1.0"
            if intrinsics_in_odometry:
                row += ", 1599.7, 1599.7, 955.5, 717.8"
            fh.write(row + "\n")
    for i in range(frames):
        Image.fromarray(np.full(shape, depth_value, dtype=np.uint16)).save(
            root / depth_dir / f"{i:06d}.png"
        )
        if confidence:
            Image.fromarray(np.full(shape, 2, dtype=np.uint8)).save(
                root / "confidence" / f"{i:06d}.png"
            )
    return root


def test_build_bundle_round_trips_and_synthesises_confidence(tmp_path: Path) -> None:
    raw = _raw_export(tmp_path / "raw", frames=3, confidence=False)
    out = build_bundle(raw, tmp_path / "bundles", capture_id="aaaa1111")
    bundle = load_bundle(out)
    assert bundle.capture_id == "aaaa1111"
    assert bundle.tier == "lidar"
    assert bundle.n_frames == 3
    assert len(bundle.depth_frames) == 3
    # confidence was absent -> synthesised all-2 so the stage-1 gate can fire
    assert len(bundle.conf_frames) == 3
    conf = np.asarray(Image.open(out / "confidence" / "000000.png"))
    assert conf.dtype == np.uint8 and set(np.unique(conf)) == {2}
    # meta.json records the capture provenance (plan 09 disclosure)
    meta = json.loads((out / "meta.json").read_text())
    assert meta["tier"] == "lidar"
    assert meta["tool"]["name"] == "LiDAR Logger" if "tool" in meta else True


def test_build_bundle_meta_and_device(tmp_path: Path) -> None:
    raw = _raw_export(tmp_path / "raw")
    out = build_bundle(
        raw,
        tmp_path / "bundles",
        device="iPhone 15 Pro",
        ios="iOS 18.1",
        app="LiDAR Logger",
        app_version="1.2",
        rooms_expected=2,
    )
    meta = json.loads((out / "meta.json").read_text())
    assert meta == {
        "tier": "lidar",
        "rooms_expected": 2,
        "device": "iPhone 15 Pro",
        "ios": "iOS 18.1",
        "tool": {"name": "LiDAR Logger", "version": "1.2"},
    }


def test_build_bundle_converts_metres_to_millimetres(tmp_path: Path) -> None:
    # depth_m/ holds metres (value 2 == 2 m); the bundle must store millimetres (2000).
    raw = _raw_export(tmp_path / "raw", depth_dir="depth_m", depth_value=2)
    out = build_bundle(raw, tmp_path / "bundles")
    depth = np.asarray(Image.open(out / "depth" / "000000.png"))
    assert depth.dtype == np.uint16 and int(depth[0, 0]) == 2000


def test_build_bundle_recovers_intrinsics_from_odometry(tmp_path: Path) -> None:
    raw = _raw_export(tmp_path / "raw", camera_matrix=False)
    out = build_bundle(raw, tmp_path / "bundles")
    # K was absent: derived from the odometry row and written for the loader
    k = np.loadtxt(out / "camera_matrix.csv", delimiter=",")
    assert k.shape == (3, 3) and abs(k[0, 0] - 1599.7) < 1e-6
    assert load_bundle(out).n_frames == 3


def test_build_bundle_rejects_bad_depth_shape(tmp_path: Path) -> None:
    raw = _raw_export(tmp_path / "raw", shape=(8, 8))
    with pytest.raises(BundleBuildError, match="256x192"):
        build_bundle(raw, tmp_path / "bundles")


def test_build_bundle_rejects_missing_odometry(tmp_path: Path) -> None:
    raw = _raw_export(tmp_path / "raw")
    (raw / "odometry.csv").unlink()
    with pytest.raises(BundleBuildError, match="odometry.csv not found"):
        build_bundle(raw, tmp_path / "bundles")


def test_build_bundle_rejects_unrecoverable_intrinsics(tmp_path: Path) -> None:
    raw = _raw_export(tmp_path / "raw", camera_matrix=False, intrinsics_in_odometry=False)
    with pytest.raises(BundleBuildError, match="cannot recover intrinsics"):
        build_bundle(raw, tmp_path / "bundles")
