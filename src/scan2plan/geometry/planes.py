"""Horizontal plane (floor/ceiling) detection from a world point cloud.

Plan 04c section 1.1: the world frame is gravity-aligned (Y-up), so floors and
ceilings are horizontal planes (constant world Y). We find them as peaks in the
world-Y histogram. Depth scale was verified in B-0 (ADR-0002).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class HorizontalPlane:
    """A detected horizontal plane at world height ``height_m``."""

    height_m: float
    rms_m: float  # RMS residual of points within +/-3 cm of the plane
    support: float  # fraction of all points within +/-3 cm of the plane


def horizontal_planes(
    y: NDArray[np.float64],
    *,
    bin_w: float = 0.01,
    min_sep_m: float = 1.8,
    max_planes: int = 2,
    min_support: float = 0.02,
    prominence: float = 2.5,
) -> list[HorizontalPlane]:
    """Return dominant horizontal planes sorted low->high (floor first, ceiling next).

    A plane is kept only if at least ``min_support`` of all points lie within
    +/-3 cm of it; adjacent peaks must be separated by >= ``min_sep_m`` (a room
    ceiling is a room-height above the floor, so furniture planes are ignored).
    """
    if y.size == 0:
        return []
    lo, hi = float(np.min(y)), float(np.max(y))
    edges = np.arange(lo - 0.05, hi + bin_w + 0.05, bin_w)  # pad so edge planes are seen
    hist, edges = np.histogram(y, bins=edges)
    centers = (edges[:-1] + edges[1:]) / 2
    smooth = np.convolve(hist, np.ones(5) / 5, mode="same")

    # Background = median density over occupied bins; a real plane is a sharp peak.
    occupied = hist > 0
    background = float(np.median(smooth[occupied])) if occupied.any() else 1.0

    candidates = [
        i
        for i in range(len(smooth))
        if smooth[i] >= (smooth[i - 1] if i > 0 else 0.0)
        and smooth[i] >= (smooth[i + 1] if i < len(smooth) - 1 else 0.0)
        and smooth[i] >= prominence * background
    ]
    candidates.sort(key=lambda i: smooth[i], reverse=True)

    picked: list[int] = []
    for i in candidates:
        if all(abs(centers[i] - centers[j]) >= min_sep_m for j in picked):
            picked.append(i)
        if len(picked) == max_planes:
            break

    n = float(y.size)
    planes: list[HorizontalPlane] = []
    for i in sorted(picked):
        near0 = np.abs(y - centers[i]) <= 0.03
        # Centroid of the plane band (the smoothed peak is a plateau, not a point).
        height = float(y[near0].mean()) if near0.any() else float(centers[i])
        near = np.abs(y - height) <= 0.03
        support = float(near.sum()) / n
        if support < min_support:
            continue
        rms = float(np.std(y[near])) if int(near.sum()) else float("nan")
        planes.append(
            HorizontalPlane(
                height_m=round(height, 4), rms_m=round(rms, 4), support=round(support, 4)
            )
        )
    return planes
