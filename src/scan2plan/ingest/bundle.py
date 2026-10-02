"""Read an interface-I1 capture bundle (plan 04b, stage S1).

Mirrors ``docs/plans/01-shared-conventions-and-interfaces.md`` section 6 exactly:
``odometry.csv`` (per-frame pose + intrinsics), ``camera_matrix.csv`` (3x3 K),
``depth/`` (uint16 mm) + ``confidence/`` (uint8 {0,1,2}), ``rgb.mp4``, optional
``meta.json``, optional ``photos/``.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from scan2plan.cir.measure import Tier

#: Depth / confidence frame grid (the RGB frame is 1920x1440).
DEPTH_SHAPE = (192, 256)


class BundleError(ValueError):
    """Raised when an I1 bundle is missing or has unreadable required inputs."""


@dataclass(frozen=True)
class OdometryRow:
    """One odometry row: pose (camera->world) + per-frame intrinsics."""

    timestamp: float
    frame: str
    position: tuple[float, float, float]
    quaternion: tuple[float, float, float, float]  # xyzw
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass
class CaptureBundle:
    """A parsed I1 bundle: tier-detected, with per-frame pose data."""

    capture_dir: Path
    group: str
    capture_id: str
    tier: Tier
    odometry: list[OdometryRow]
    camera_matrix: NDArray[np.float64]
    rgb_ref: str
    depth_frames: set[str] = field(default_factory=set)
    conf_frames: set[str] = field(default_factory=set)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n_frames(self) -> int:
        return len(self.odometry)


def detect_tier(capture_dir: Path) -> Tier:
    """Infer the input tier (I1 §6): depth/ => lidar, else photos/ => photos, else video."""
    if (capture_dir / "depth").is_dir():
        return "lidar"
    if (capture_dir / "photos").is_dir():
        return "photos"
    return "video"


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open() as fh:
            return [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(fh)]
    except FileNotFoundError as exc:
        raise BundleError(f"missing required file: {path}") from exc


def _opt_float(row: dict[str, str], key: str, default: float) -> float:
    value = row.get(key, "")
    return float(value) if value not in ("", None) else default


def load_bundle(capture_dir: str | Path) -> CaptureBundle:
    """Parse and sanity-check an I1 bundle; raise BundleError on hard failure."""
    cap = Path(capture_dir)
    if not cap.is_dir():
        raise BundleError(f"capture dir not found: {cap}")

    odo_path = cap / "odometry.csv"
    k_path = cap / "camera_matrix.csv"
    if not odo_path.is_file():
        raise BundleError(f"odometry.csv not found in {cap}")
    if not k_path.is_file():
        raise BundleError(f"camera_matrix.csv not found in {cap}")
    camera_matrix = np.loadtxt(k_path, delimiter=",", dtype=np.float64)

    odometry = [
        OdometryRow(
            timestamp=float(r["timestamp"]),
            frame=r["frame"],
            position=(float(r["x"]), float(r["y"]), float(r["z"])),
            quaternion=(float(r["qx"]), float(r["qy"]), float(r["qz"]), float(r["qw"])),
            fx=_opt_float(r, "fx", float(camera_matrix[0, 0])),
            fy=_opt_float(r, "fy", float(camera_matrix[1, 1])),
            cx=_opt_float(r, "cx", float(camera_matrix[0, 2])),
            cy=_opt_float(r, "cy", float(camera_matrix[1, 2])),
        )
        for r in _read_rows(odo_path)
    ]
    if not odometry:
        raise BundleError(f"odometry.csv has no rows in {cap}")

    depth_dir, conf_dir = cap / "depth", cap / "confidence"
    depth_frames = {p.name for p in depth_dir.glob("*.png")} if depth_dir.is_dir() else set()
    conf_frames = {p.name for p in conf_dir.glob("*.png")} if conf_dir.is_dir() else set()

    meta: dict[str, Any] = {}
    meta_path = cap / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text())

    return CaptureBundle(
        capture_dir=cap,
        group=cap.parent.name,
        capture_id=cap.name,
        tier=detect_tier(cap),
        odometry=odometry,
        camera_matrix=camera_matrix,
        rgb_ref="rgb.mp4",
        depth_frames=depth_frames,
        conf_frames=conf_frames,
        meta=meta,
    )
