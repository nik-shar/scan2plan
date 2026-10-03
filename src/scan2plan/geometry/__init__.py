"""Stage S3: point cloud -> rooms/surfaces/openings (plan 04c/04h/04i)."""

from __future__ import annotations

from scan2plan.geometry.extract import RoomGeometry, estimate_orientation, extract_room
from scan2plan.geometry.footprint import (
    Footprint2D,
    extract_footprint,
    merge_collinear,
    occupancy_grid,
)
from scan2plan.geometry.planes import HorizontalPlane, horizontal_planes
from scan2plan.geometry.room_outline import (
    OutlineResult,
    Region,
    WallState,
    build_outline,
    wall_params_from_config,
)
from scan2plan.geometry.wall_model import WallParams

__all__ = [
    "Footprint2D",
    "HorizontalPlane",
    "OutlineResult",
    "Region",
    "RoomGeometry",
    "WallParams",
    "WallState",
    "build_outline",
    "estimate_orientation",
    "extract_footprint",
    "extract_room",
    "horizontal_planes",
    "merge_collinear",
    "occupancy_grid",
    "wall_params_from_config",
]
