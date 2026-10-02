"""Coordinate-frame and camera-math helpers (interface I7).

Conventions (docs/plans/01-shared-conventions-and-interfaces.md section 4):
  world  : right-handed, Y-up, gravity-aligned.
  camera : ARKit camera, +X right, +Y up, -Z forward.
  pose   : (x, y, z, qx, qy, qz, qw) is camera->world, quaternion order xyzw.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

Mat3 = NDArray[np.float64]
Mat4 = NDArray[np.float64]


def quat_xyzw_to_matrix(qx: float, qy: float, qz: float, qw: float) -> Mat3:
    """Convert a unit quaternion (x, y, z, w) to a 3x3 rotation matrix."""
    n = np.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if n == 0.0:
        raise ValueError("zero-norm quaternion")
    x, y, z, w = qx / n, qy / n, qz / n, qw / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def pose_from_xyz_quat(
    x: float, y: float, z: float, qx: float, qy: float, qz: float, qw: float
) -> Mat4:
    """Build the 4x4 camera->world transform T_wc from a translation + quaternion."""
    t = np.eye(4, dtype=np.float64)
    t[:3, :3] = quat_xyzw_to_matrix(qx, qy, qz, qw)
    t[:3, 3] = (x, y, z)
    return t


def scale_intrinsics(k: Mat3, sx: float, sy: float) -> Mat3:
    """Rescale a 3x3 intrinsic matrix by image-size factors (sx, sy)."""
    out = np.array(k, dtype=np.float64, copy=True)
    out[0, 0] *= sx
    out[0, 2] *= sx
    out[1, 1] *= sy
    out[1, 2] *= sy
    return out


def depth_to_points(depth_m: NDArray[np.float64], k: Mat3) -> NDArray[np.float64]:
    """Back-project a depth map (metres, HxW) to an Nx3 camera-frame point cloud.

    Pixels with non-positive depth are dropped.
    """
    h, w = depth_m.shape
    ys, xs = np.nonzero(depth_m > 0.0)
    z = depth_m[ys, xs]
    fx, fy = k[0, 0], k[1, 1]
    cx, cy = k[0, 2], k[1, 2]
    x = (xs - cx) * z / fx
    y = (ys - cy) * z / fy
    return np.column_stack([x, y, z]).astype(np.float64)
