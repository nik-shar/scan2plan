"""SE(2) pose-graph optimization (plan 04d section 2.4, task S-3).

Variables are ``(x, y, theta)`` per room in the plan frame; the anchor room is
held fixed. Each connector/loop-closure constraint contributes the residual
``log(meas^-1 . (T_wb^-1 T_wa))`` weighted by the measurement's confidence. Solved
with ``scipy.optimize.least_squares`` (the plan-04d default); the solver is
deterministic given the initial guesses, which come from odometry/connectors -
never from an RNG - so the determinism contract (01 section 7) holds by
construction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from scipy.optimize import least_squares

from scan2plan.cir import SE2
from scan2plan.stitch.se2 import relative, wrap_angle


class Constraint(NamedTuple):
    """A weighted relative-pose measurement ``T_ab``: maps room-``a`` frame points
    into room-``b``'s frame (``p_b = T_ab @ p_a``). The graph estimate for it is
    ``T_wb^-1 . T_wa`` where ``T_wi`` places room ``i`` in the plan frame."""

    room_a: str
    room_b: str
    meas: SE2
    weight: float


@dataclass(frozen=True)
class OptimizeResult:
    """Optimized plan-frame transforms plus fit diagnostics."""

    transforms: dict[str, SE2]
    mean_residual: float  # mean |weighted residual| over all constraints
    n_constraints: int


def _post_gap(cons: Constraint, transforms: dict[str, SE2]) -> float:
    """Translation residual of a constraint under the final estimate (metres)."""
    est = relative(transforms[cons.room_b], transforms[cons.room_a])
    err = relative(cons.meas, est)
    return float(math.hypot(err.x, err.y))


def optimize_pose_graph(
    room_ids: list[str],
    initials: dict[str, SE2],
    constraints: list[Constraint],
    *,
    anchor: str | None = None,
) -> OptimizeResult:
    """Optimize plan-frame room transforms against the given constraints.

    Rooms without any constraint keep their initial transform. With no
    constraints at all the initials are returned unchanged (degenerate graph).
    """
    ids = sorted(room_ids)
    anchor = anchor or ids[0]
    free = [r for r in ids if r != anchor]
    if not constraints or not free:
        return OptimizeResult(dict(initials), 0.0, len(constraints))

    offset = {r: 3 * i for i, r in enumerate(free)}
    x0 = np.array(
        [[initials[r].x, initials[r].y, initials[r].theta] for r in free],
        dtype=np.float64,
    ).ravel()

    def unpack(x: np.ndarray) -> dict[str, SE2]:
        out = {anchor: initials[anchor]}
        for r in free:
            i = offset[r]
            out[r] = SE2(x=float(x[i]), y=float(x[i + 1]), theta=float(x[i + 2]))
        return out

    def residual(x: np.ndarray) -> np.ndarray:
        t = unpack(x)
        rows: list[list[float]] = []
        for cons in constraints:
            est = relative(t[cons.room_b], t[cons.room_a])
            err = relative(cons.meas, est)
            w = math.sqrt(max(cons.weight, 0.0))
            rows.append([err.x * w, err.y * w, wrap_angle(err.theta) * w])
        return np.array(rows, dtype=np.float64).ravel()

    # trf handles underdetermined graphs (fewer residuals than variables).
    sol = least_squares(residual, x0, method="trf")
    r = residual(sol.x)
    return OptimizeResult(unpack(sol.x), float(np.mean(np.abs(r))), len(constraints))
