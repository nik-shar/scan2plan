"""Turn a world point cloud into room/surface/opening CIR entities (plan 04c/04i).

S3 delegates the outline to the three-stage process in ``room_outline``
(stage 1 observed -> stage 2 classify -> stage 3 final walls), whose wall finding
is the ported ``wall_model`` logic (plan 04i). This module keeps the small public
surface the rest of the pipeline imports (``RoomGeometry``, ``extract_room``,
``estimate_orientation``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from scan2plan.cir import Measurement, Opening, Room, Surface
from scan2plan.cir.measure import Tier
from scan2plan.config import Config
from scan2plan.geometry.footprint import rotate2d
from scan2plan.geometry.planes import horizontal_planes
from scan2plan.geometry.room_outline import build_outline

# Robust (percentile) extents for the orientation estimate (plan 04c section 1.2).
OBB_PCT_LO = 1.0
OBB_PCT_HI = 99.0


@dataclass
class RoomGeometry:
    """The CIR entities produced for one room (S3 output)."""

    room: Room
    surfaces: list[Surface] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    measures: list[Measurement] = field(default_factory=list)


def estimate_orientation(xz: NDArray[np.float64], step_deg: float = 1.0) -> float:
    """Manhattan orientation: yaw minimising the (robust) bounding-box area."""
    best_theta, best_area = 0.0, np.inf
    for deg in np.arange(0.0, 90.0, step_deg):
        theta = float(np.deg2rad(deg))
        rot = rotate2d(xz, theta)
        xs = np.percentile(rot[:, 0], [OBB_PCT_LO, OBB_PCT_HI])
        zs = np.percentile(rot[:, 1], [OBB_PCT_LO, OBB_PCT_HI])
        area = float((xs[1] - xs[0]) * (zs[1] - zs[0]))
        if area < best_area:
            best_area, best_theta = area, theta
    return best_theta


def extract_room(
    points: NDArray[np.float64],
    *,
    tier: Tier,
    seed: int = 1337,
    room_id: str = "room_0",
    name: str | None = None,
    cam_xyz: NDArray[np.float64] | None = None,
    cfg: Config | None = None,
    floor_y: float | None = None,
    ceil_y: float | None = None,
) -> RoomGeometry:
    """Build room + surfaces + openings via the three-stage outline (plan 04i).

    ``cam_xyz`` is the camera path (the wall fitter uses it to know the room
    interior); when absent the point-cloud centroid is used as a stand-in.
    """
    if points.size == 0:
        raise ValueError("empty point cloud")
    if floor_y is None:
        planes = horizontal_planes(points[:, 1])
        if not planes:
            raise ValueError("no floor plane detected")
        floor_y = planes[0].height_m
        if ceil_y is None and len(planes) > 1:
            ceil_y = planes[1].height_m

    config = cfg or Config()
    if config.seed != seed:
        config = config.model_copy(update={"seed": seed})
    cam = (
        cam_xyz
        if cam_xyz is not None and cam_xyz.shape[0] > 0
        else np.mean(points, axis=0)[None, :]
    )
    res = build_outline(
        points,
        cam.astype(np.float64),
        tier=tier,
        floor_y=float(floor_y),
        ceil_y=ceil_y,
        cfg=config,
        room_id=room_id,
        name=name,
    )
    return RoomGeometry(
        room=res.room, surfaces=res.surfaces, openings=res.openings, measures=res.measures
    )
