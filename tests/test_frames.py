"""Tests for coordinate-frame / camera math (interface I7, plan 02 task F-5)."""

from __future__ import annotations

import numpy as np
import pytest

from scan2plan.util.frames import (
    depth_to_points,
    pose_from_xyz_quat,
    quat_xyzw_to_matrix,
    scale_intrinsics,
)


def test_identity_quaternion_gives_identity() -> None:
    assert np.allclose(quat_xyzw_to_matrix(0.0, 0.0, 0.0, 1.0), np.eye(3))


def test_rotation_matrix_is_orthonormal() -> None:
    r = quat_xyzw_to_matrix(0.71036303, -0.58647335, -0.07790033, 0.38126758)
    assert np.allclose(r @ r.T, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(r), 1.0)


def test_quaternion_is_normalised() -> None:
    r = quat_xyzw_to_matrix(0.0, 0.0, 0.0, 2.0)  # non-unit w
    assert np.allclose(r, np.eye(3))


def test_zero_quaternion_raises() -> None:
    with pytest.raises(ValueError, match="zero-norm"):
        quat_xyzw_to_matrix(0.0, 0.0, 0.0, 0.0)


def test_pose_from_xyz_quat_places_translation() -> None:
    t = pose_from_xyz_quat(1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0)
    assert t.shape == (4, 4)
    assert np.allclose(t[:3, 3], [1.0, 2.0, 3.0])
    assert np.allclose(t[3], [0.0, 0.0, 0.0, 1.0])
    assert np.allclose(t[:3, :3], np.eye(3))


def test_scale_intrinsics_scales_focal_and_centre() -> None:
    k = np.array([[1599.6957, 0.0, 955.5105], [0.0, 1599.6957, 717.8084], [0.0, 0.0, 1.0]])
    out = scale_intrinsics(k, 256 / 1920, 192 / 1440)
    assert np.isclose(out[0, 0], 1599.6957 * (256 / 1920))
    assert np.isclose(out[0, 2], 955.5105 * (256 / 1920))
    assert np.isclose(out[1, 1], 1599.6957 * (192 / 1440))
    assert np.isclose(out[1, 2], 717.8084 * (192 / 1440))
    # original must be untouched
    assert np.isclose(k[0, 0], 1599.6957)


def test_depth_to_points_back_projection() -> None:
    depth = np.array([[0.0, 1.0], [2.0, 0.0]])
    k = np.eye(3)  # fx = fy = 1, cx = cy = 0
    pts = depth_to_points(depth, k)
    # nonzero pixels in row-major order: (y=0, x=1, z=1) then (y=1, x=0, z=2)
    assert np.allclose(pts, [[1.0, 0.0, 1.0], [0.0, 2.0, 2.0]])


def test_depth_to_points_drops_nonpositive() -> None:
    depth = np.zeros((3, 3))
    assert depth_to_points(depth, np.eye(3)).shape == (0, 3)
