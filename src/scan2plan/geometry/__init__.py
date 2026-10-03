"""Geometry: stage-1 evidence + shared primitives (plan 04i).

Stage 2/3 (outline tracing, classification, snapping) were moved to
``archive/old_stage23/`` for redesign. ``room_fit`` is kept as an unused reference.
"""

from __future__ import annotations

from scan2plan.geometry.evidence import (
    EVIDENCE_LAYER_CAP,
    camera_travel_m,
    observed_evidence,
    wall_cells_with_support,
)
from scan2plan.geometry.planes import HorizontalPlane, horizontal_planes

__all__ = [
    "EVIDENCE_LAYER_CAP",
    "HorizontalPlane",
    "camera_travel_m",
    "horizontal_planes",
    "observed_evidence",
    "wall_cells_with_support",
]
