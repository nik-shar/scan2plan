"""Stage S3: point cloud -> rooms/surfaces/openings (plan 04c/04h)."""

from __future__ import annotations

from scan2plan.geometry.extract import RoomGeometry, estimate_orientation, extract_room
from scan2plan.geometry.footprint import (
    Footprint2D,
    extract_footprint,
    merge_collinear,
    occupancy_grid,
)
from scan2plan.geometry.planes import HorizontalPlane, horizontal_planes

__all__ = [
    "Footprint2D",
    "HorizontalPlane",
    "RoomGeometry",
    "estimate_orientation",
    "extract_footprint",
    "extract_room",
    "horizontal_planes",
    "merge_collinear",
    "occupancy_grid",
]
