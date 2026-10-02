"""CIR package (interfaces I2/I3/I6; plan 04a).

Import the frozen contract from here; do not redefine it elsewhere (rule R2).
"""

from __future__ import annotations

from scan2plan.cir.measure import Measurement, Tier
from scan2plan.cir.model import (
    CIR,
    SCHEMA_VERSION,
    SE2,
    Ablation,
    ConcealedFlag,
    Damage,
    DamageClass,
    Extent,
    Footprint,
    Frame,
    LoopClosure,
    ModelRef,
    Opening,
    OpeningKind,
    Plane,
    Provenance,
    Recon,
    ReconQuality,
    Room,
    ScopeItem,
    Session,
    Stitch,
    StitchEdge,
    Surface,
    SurfaceType,
    Tool,
)

__all__ = [
    "SCHEMA_VERSION",
    "CIR",
    "Ablation",
    "ConcealedFlag",
    "Damage",
    "DamageClass",
    "Extent",
    "Footprint",
    "Frame",
    "LoopClosure",
    "Measurement",
    "ModelRef",
    "Opening",
    "OpeningKind",
    "Plane",
    "Provenance",
    "Recon",
    "ReconQuality",
    "Room",
    "SE2",
    "ScopeItem",
    "Session",
    "Stitch",
    "StitchEdge",
    "Surface",
    "SurfaceType",
    "Tier",
    "Tool",
]
