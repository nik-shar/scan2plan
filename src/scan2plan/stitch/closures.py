"""Loop-closure (revisit) detection (plan 04d section 2.3, task S-2).

A revisit is two room polygons that **overlap in the current placement** without a
connector edge between them - e.g. a corridor scanned twice, or the same room
re-entered from another door. The corrective relative transform is estimated with
deterministic point-to-point ICP (2D Kabsch under a ``cKDTree`` nearest-neighbour
lookup, seeded only by the current placement, so no RNG is involved).

The translation magnitude of the correction is the **closure gap**: hard, per-
capture evidence of accumulated drift (G-DRIFT forbids consuming poses as-is).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree
from shapely.geometry import Polygon

from scan2plan.cir import SE2
from scan2plan.stitch.polygons import boundary_points

#: Minimum interior overlap for a polygon pair to count as a revisit (m2).
MIN_OVERLAP_M2 = 0.25
#: Corrections smaller than this add no information (already consistent).
MIN_GAP_M = 0.01


@dataclass(frozen=True)
class ClosureMatch:
    """A detected revisit constraint between two rooms.

    ``correction`` is the plan-frame SE(2) that moves room ``a``'s current
    placement onto room ``b``'s (ICP estimate); ``gap_m`` is its translation
    magnitude (pre-optimization drift evidence); ``weight`` grows with overlap
    area and falls with the ICP residual.
    """

    room_a: str
    room_b: str
    correction: SE2
    weight: float
    gap_m: float


def icp_correction(
    src: NDArray[np.float64],
    dst: NDArray[np.float64],
    *,
    iters: int = 30,
    tol: float = 1e-6,
) -> tuple[SE2, float]:
    """Point-to-point ICP aligning ``src`` onto ``dst``; returns (SE2, mean dist).

    Fully deterministic: fixed initial guess (identity), exact nearest
    neighbours, closed-form Kabsch updates, fixed iteration cap.
    """
    tree = cKDTree(dst)
    rot = np.eye(2)
    trans = np.zeros(2)
    prev = np.inf
    mean_d = np.inf
    for _ in range(iters):
        moved = (rot @ src.T).T + trans
        dist, idx = tree.query(moved)
        matched = dst[idx]
        cx, cy = moved.mean(axis=0), matched.mean(axis=0)
        h = (moved - cx).T @ (matched - cy)
        u, _, vt = np.linalg.svd(h)
        fix = np.diag([1.0, np.sign(np.linalg.det(vt.T @ u.T))])
        r_d = vt.T @ fix @ u.T
        t_d = cy - r_d @ cx
        rot = r_d @ rot
        trans = r_d @ trans + t_d
        mean_d = float(dist.mean())
        if abs(prev - mean_d) < tol:
            break
        prev = mean_d
    theta = float(np.arctan2(rot[1, 0], rot[0, 0]))
    return SE2(x=float(trans[0]), y=float(trans[1]), theta=theta), mean_d


def detect_closures(
    polys: dict[str, Polygon],
    *,
    eligible: set[str] | None = None,
    min_overlap_m2: float = MIN_OVERLAP_M2,
    min_gap_m: float = MIN_GAP_M,
) -> list[ClosureMatch]:
    """Find revisit constraints between overlapping, non-connector room pairs.

    ``eligible`` restricts detection to pairs touching the anchor-connected
    component: two *unplaced* rooms both sitting at their local origin would
    otherwise produce a spurious full-overlap closure (photo-tier guard, 04d
    section 5).
    """
    out: list[ClosureMatch] = []
    ids = sorted(polys)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if eligible is not None and not ({a, b} & eligible):
                continue
            inter = float(polys[a].intersection(polys[b]).area)
            if inter < min_overlap_m2:
                continue
            corr, fit = icp_correction(boundary_points(polys[a]), boundary_points(polys[b]))
            gap = float(np.hypot(corr.x, corr.y))
            if gap < min_gap_m:
                continue  # already consistent; nothing to correct
            weight = min(1.0, inter / 2.0) / (1.0 + fit / 0.05)
            out.append(
                ClosureMatch(
                    room_a=a,
                    room_b=b,
                    correction=corr,
                    weight=round(weight, 3),
                    gap_m=round(gap, 4),
                )
            )
    return out
