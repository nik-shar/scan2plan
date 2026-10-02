"""Stage S4: multi-room stitching, drift correction and ablation (plan 04d).

Consumes ``rooms[]``/``surfaces[]``/``openings[]`` from S3 (04c) and produces the
CIR ``stitch{}`` block (I2). The same entry point serves the G-DRIFT ablation via
``run_ablation`` (loop closure on/off from one code path).
"""

from __future__ import annotations

from scan2plan.stitch.closures import ClosureMatch, detect_closures, icp_correction
from scan2plan.stitch.core import OVERLAP_TOL_M2, run_ablation, run_stitch
from scan2plan.stitch.graph import match_connectors
from scan2plan.stitch.optimize import Constraint, OptimizeResult, optimize_pose_graph
from scan2plan.stitch.se2 import SE2, apply, compose, inverse, relative, wrap_angle

__all__ = [
    "OVERLAP_TOL_M2",
    "SE2",
    "ClosureMatch",
    "Constraint",
    "OptimizeResult",
    "apply",
    "compose",
    "detect_closures",
    "icp_correction",
    "inverse",
    "match_connectors",
    "optimize_pose_graph",
    "relative",
    "run_ablation",
    "run_stitch",
    "wrap_angle",
]
