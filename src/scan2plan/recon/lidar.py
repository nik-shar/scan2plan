"""Stage S2 (LiDAR tier): back-project depth into a world point cloud (plan 04b §3).

Steps: parse poses (done in S1) -> scale K to the 256x192 depth grid -> back-project
(pinhole, per ADR-0002) -> transform to world via T_wc -> filter confidence>=1 and
drop depth==0 -> voxel-downsample. Metric scale comes from the LiDAR depth, so
``scale=1.0`` / ``scale_source="lidar"`` and pose data is used as reconstruction
initialisation only (drift is corrected by 04d, never "as-is").
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from scan2plan.cir import Frame, ReconQuality
from scan2plan.config import Config
from scan2plan.util.frames import depth_to_points, scale_intrinsics

#: K applies to the 1920x1440 RGB frame; depth/confidence are 256x192 (I7 section 4).
DEPTH_SCALE_XY = (256.0 / 1920.0, 192.0 / 1440.0)


def voxel_downsample(points: NDArray[np.float64], voxel_m: float) -> NDArray[np.float64]:
    """Keep one representative point per voxel (deterministic, input order)."""
    if points.size == 0 or voxel_m <= 0.0:
        return points
    keys = np.floor(points / voxel_m).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    return points[np.sort(first)]


def _frame_world_points(
    capture_dir: Path, frame: Frame, config: Config, *, filters: bool = True
) -> NDArray[np.float64]:
    if frame.depth_ref is None or frame.pose is None or frame.K is None:
        return np.empty((0, 3), dtype=np.float64)
    depth = np.asarray(Image.open(capture_dir / frame.depth_ref)).astype(np.float64)
    depth = depth * config.depth_scale_m  # uint16 -> metres
    if filters:
        # Stage-1 gates (plan 04i): drop out-of-range returns and low-confidence depth.
        depth = np.where(depth <= config.outline.max_range_m, depth, 0.0)
        if frame.conf_ref is not None:
            conf = np.asarray(Image.open(capture_dir / frame.conf_ref)).astype(np.uint8)
            depth = np.where(conf >= config.outline.confidence_min, depth, 0.0)
    k = scale_intrinsics(np.array(frame.K, dtype=np.float64).reshape(3, 3), *DEPTH_SCALE_XY)
    cam = depth_to_points(depth, k)
    if cam.size == 0:
        return np.empty((0, 3), dtype=np.float64)
    t_wc = np.array(frame.pose, dtype=np.float64).reshape(4, 4)
    return (t_wc[:3, :3] @ cam.T).T + t_wc[:3, 3]


def _floor_rms(points: NDArray[np.float64]) -> float | None:
    """RMS world-Y residual of the dominant floor plane (a recon quality signal)."""
    if points.size == 0:
        return None
    y = points[:, 1]
    floor_y = float(np.percentile(y, 2.0))
    near = y[np.abs(y - floor_y) <= 0.05]
    return round(float(np.std(near)), 4) if near.size else None


def reconstruct_lidar(
    capture_dir: Path,
    frames: list[Frame],
    config: Config,
    *,
    stride: int = 20,
    voxel_m: float = 0.01,
    filters: bool = True,
) -> tuple[NDArray[np.float64], ReconQuality]:
    """Build the world point cloud + quality metrics from sampled frames."""
    sampled = frames[::stride] if stride > 1 else frames
    chunks: list[NDArray[np.float64]] = []
    used = 0
    coverage_acc: list[float] = []
    for frame in sampled:
        world = _frame_world_points(capture_dir, frame, config, filters=filters)
        if frame.depth_ref is not None:
            depth = np.asarray(Image.open(capture_dir / frame.depth_ref))
            coverage_acc.append(float(np.mean(depth > 0)))
        if world.size:
            chunks.append(voxel_downsample(world, voxel_m))
            used += 1

    points = voxel_downsample(np.vstack(chunks), voxel_m) if chunks else np.empty((0, 3))
    quality = ReconQuality(
        track_len=float(used),
        coverage=round(float(np.mean(coverage_acc)), 4) if coverage_acc else None,
        plane_rms=_floor_rms(points),
        scale_uncertainty=None,  # metric LiDAR depth -> no scale uncertainty
    )
    return points, quality
