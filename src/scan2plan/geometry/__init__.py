"""Geometry: stage-1 evidence + stage-2 wall reconstruction (plan 04i).

Stage 1 is the frozen observed-evidence layer; stage 2 reconstructs walls from
that artifact only. Stage 3 (closing/classification) is still being redesigned;
``room_fit`` is kept as an unused reference.
"""

from __future__ import annotations

from scan2plan.geometry.evidence import (
    EVIDENCE_LAYER_CAP,
    camera_travel_m,
    observed_evidence,
    wall_cells_with_support,
)
from scan2plan.geometry.planes import HorizontalPlane, horizontal_planes
from scan2plan.geometry.wall_complete import (
    CompletionParams,
    CompletionResult,
    WallPiece,
    complete_walls,
    completion_params_from_config,
)
from scan2plan.geometry.wall_graph import (
    GraphEdge,
    GraphNode,
    GraphParams,
    WallGraph,
    build_wall_graph,
    graph_params_from_config,
)
from scan2plan.geometry.walls import (
    AXES,
    Segment,
    WallParams,
    explained_mask,
    reconstruct_walls,
    wall_params_from_config,
)

__all__ = [
    "AXES",
    "EVIDENCE_LAYER_CAP",
    "HorizontalPlane",
    "Segment",
    "WallParams",
    "CompletionParams",
    "CompletionResult",
    "GraphEdge",
    "GraphNode",
    "GraphParams",
    "WallGraph",
    "WallPiece",
    "build_wall_graph",
    "camera_travel_m",
    "complete_walls",
    "completion_params_from_config",
    "explained_mask",
    "graph_params_from_config",
    "horizontal_planes",
    "observed_evidence",
    "reconstruct_walls",
    "wall_cells_with_support",
    "wall_params_from_config",
]
