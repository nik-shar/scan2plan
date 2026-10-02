"""Stage S3: point cloud -> rooms/surfaces/openings (plan 04c)."""

from __future__ import annotations

from scan2plan.geometry.extract import RoomGeometry, estimate_orientation, extract_room
from scan2plan.geometry.planes import HorizontalPlane, horizontal_planes

__all__ = [
    "HorizontalPlane",
    "RoomGeometry",
    "estimate_orientation",
    "extract_room",
    "horizontal_planes",
]
