"""Stages S5-S7: damage, concealed flags & scope line items (plan 04e).

Public entry point is :func:`scan2plan.damage.assess.assess`, which turns the CIR
surfaces + the raw capture frames into ``damages[]`` (OUT-3), ``concealed[]``
(OUT-4) and ``scope[]`` (OUT-5), plus a ``damage.json`` sidecar recording every
threshold that fired.

The region proposer is a **disclosed colour heuristic** over depth-projected
surface evidence (no ML runtime is required); the SAM/CLIP model hook from plan
04e is documented in ``docs/plans/09`` and can replace :mod:`detect` behind the
same :class:`scan2plan.cir.Damage` contract.
"""

from __future__ import annotations

from scan2plan.damage.assess import Assessment, assess
from scan2plan.damage.detect import detect_damages
from scan2plan.damage.evidence import SurfaceGrid, build_surface_evidence
from scan2plan.damage.rules import concealed_flags
from scan2plan.damage.scope import scope_items

__all__ = [
    "Assessment",
    "SurfaceGrid",
    "assess",
    "build_surface_evidence",
    "concealed_flags",
    "detect_damages",
    "scope_items",
]
