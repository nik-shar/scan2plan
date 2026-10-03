"""Stage S2 dispatcher: per-tier reconstruction into CIR ``recon`` (plan 04b).

Only the LiDAR front-end is implemented at M1 (B-1); photos/video land at B-2/B-3.
All tiers emit the same ``Recon`` shape so downstream stages (04c/04d) stay
tier-agnostic (interface I8).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from scan2plan.cir import CIR, Recon
from scan2plan.config import Config
from scan2plan.recon.lidar import reconstruct_lidar

__all__ = ["UnsupportedTierError", "reconstruct_lidar", "run_recon"]


class UnsupportedTierError(RuntimeError):
    """Raised when a tier's recon front-end is not implemented yet."""


def run_recon(
    capture_dir: Path,
    cir: CIR,
    config: Config,
    out_dir: Path,
    *,
    stride: int = 20,
    voxel_m: float = 0.01,
) -> Recon:
    """Reconstruct ``cir.frames`` and return a populated ``Recon`` (interface I8).

    Writes ``recon/points.npz`` and ``recon/poses.npz`` under ``out_dir`` and stores
    their out-dir-relative paths in the CIR (so the bundle is portable together).
    """
    tier = cir.session.tier
    if tier != "lidar":
        raise UnsupportedTierError(
            f"recon for tier '{tier}' is not implemented yet (plan 04b, tasks B-2/B-3)"
        )

    points, quality = reconstruct_lidar(
        capture_dir, cir.frames, config, stride=stride, voxel_m=voxel_m
    )

    art_dir = out_dir / "recon"
    art_dir.mkdir(parents=True, exist_ok=True)

    points_path = art_dir / "points.npz"
    np.savez_compressed(points_path, points=points.astype(np.float32))

    # Unfiltered cloud (range/confidence gates OFF) for the stage-1 evidence layer
    # (plan 04i). Written at a conventional path; not referenced by frozen I2.
    if config.outline.save_unfiltered:
        unfiltered, _ = reconstruct_lidar(
            capture_dir, cir.frames, config, stride=stride, voxel_m=voxel_m, filters=False
        )
        np.savez_compressed(art_dir / "points_unfiltered.npz", points=unfiltered.astype(np.float32))

    poses_path = art_dir / "poses.npz"
    poses = [
        np.array(frame.pose, dtype=np.float64).reshape(4, 4)
        for frame in cir.frames
        if frame.pose is not None
    ]
    np.savez_compressed(
        poses_path, poses=np.stack(poses).astype(np.float64) if poses else np.empty((0, 4, 4))
    )

    return Recon(
        points_ref=str(points_path.relative_to(out_dir)),
        pose_graph_ref=str(poses_path.relative_to(out_dir)),
        scale=1.0,
        scale_source="lidar",
        quality=quality,
    )
