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
from scan2plan.geometry.invariants import (
    Invariant,
    check_stage3_invariants,
    inscribed_radius,
    invariants_failed,
)
from scan2plan.geometry.planes import HorizontalPlane, horizontal_planes
from scan2plan.geometry.rooms import (
    RoomParams,
    build_stage3,
    room_params_from_config,
)
from scan2plan.geometry.wall_complete import (
    KIND_OPEN_SPACE,
    CompletionParams,
    CompletionResult,
    WallPiece,
    complete_walls,
    completion_params_from_config,
    merge_wall_pieces,
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
    dense_blob_mask,
    explained_mask,
    reconstruct_walls,
    wall_params_from_config,
)

__all__ = [
    "AXES",
    "EVIDENCE_LAYER_CAP",
    "Invariant",
    "KIND_OPEN_SPACE",
    "HorizontalPlane",
    "Segment",
    "WallParams",
    "CompletionParams",
    "CompletionResult",
    "GraphEdge",
    "GraphNode",
    "GraphParams",
    "RoomParams",
    "WallGraph",
    "WallPiece",
    "build_stage3",
    "build_wall_graph",
    "camera_travel_m",
    "check_stage3_invariants",
    "complete_walls",
    "completion_params_from_config",
    "dense_blob_mask",
    "explained_mask",
    "graph_params_from_config",
    "horizontal_planes",
    "inscribed_radius",
    "invariants_failed",
    "merge_wall_pieces",
    "observed_evidence",
    "reconstruct_walls",
    "room_params_from_config",
    "wall_cells_with_support",
    "wall_params_from_config",
]
