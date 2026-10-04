"""Project depth+RGB evidence onto wall surfaces (plan 04e section 1.3).

For every sampled frame the valid pixels (confidence/range gated) are back-
projected to world points with the frame pose + intrinsics (I7/I8), assigned to
the **nearest** wall plane within ``surface_tol_m``, and accumulated as colour in
a per-surface ``(height, along-wall)`` grid. The grid is the shared substrate for
region proposal (:mod:`scan2plan.damage.detect`) - no ML runtime is needed and
the result is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from scan2plan.cir import CIR, Surface
from scan2plan.config import Config
from scan2plan.damage.frames import extract_rgb_frames, read_confidence, read_depth_m
from scan2plan.util.logging import get_logger

logger = get_logger("scan2plan.damage.evidence")


@dataclass
class SurfaceGrid:
    """Accumulated colour evidence on one wall, in (along-wall, height) metres."""

    surface_id: str
    room_id: str
    a_xz: tuple[float, float]
    tangent: tuple[float, float]
    length_m: float
    cell_m: float
    h0: float
    h1: float
    floor_y: float
    rgb_sum: NDArray[np.float64]  # (nh, nu, 3) summed 0-255 RGB
    count: NDArray[np.int64]  # (nh, nu) samples

    @property
    def shape(self) -> tuple[int, int]:
        return self.count.shape

    def mean_rgb(self, min_count: int) -> NDArray[np.float64]:
        """Mean RGB per cell (NaN where the cell has fewer than ``min_count`` samples)."""
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = self.rgb_sum / np.maximum(self.count, 1)[..., None]
        mean[self.count < min_count] = np.nan
        return mean

    def cell_center(self, ih: int, iu: int) -> tuple[float, float]:
        """World (x, z) of a cell centre along the wall."""
        s = (iu + 0.5) * self.cell_m
        return (self.a_xz[0] + s * self.tangent[0], self.a_xz[1] + s * self.tangent[1])


def _wall_surfaces(surfaces: list[Surface]) -> list[Surface]:
    """Walls with a usable horizontal plane + a 2-point polygon, sorted by id."""
    out = []
    for s in surfaces:
        if s.type != "wall" or len(s.polygon) < 2 or s.plane is None:
            continue
        if abs(s.plane.normal[1]) > 0.3:  # near-vertical normal only (a wall)
            continue
        out.append(s)
    return sorted(out, key=lambda s: s.id)


def _empty_grid(surface: Surface, cfg: Config, floor_y: float) -> SurfaceGrid:
    a, b = surface.polygon[0], surface.polygon[1]
    dx, dz = b[0] - a[0], b[1] - a[1]
    length = float(np.hypot(dx, dz))
    tan = (dx / length, dz / length) if length > 1e-9 else (1.0, 0.0)
    h0, h1 = float(cfg.damage.wall_band_m[0]), float(cfg.damage.wall_band_m[1])
    nh = max(1, int(np.ceil((h1 - h0) / cfg.damage.cell_m)))
    nu = max(1, int(np.ceil(length / cfg.damage.cell_m)))
    return SurfaceGrid(
        surface_id=surface.id,
        room_id=surface.room_id,
        a_xz=(a[0], a[1]),
        tangent=tan,
        length_m=length,
        cell_m=cfg.damage.cell_m,
        h0=h0 + floor_y,
        h1=h1 + floor_y,
        floor_y=floor_y,
        rgb_sum=np.zeros((nh, nu, 3), dtype=np.float64),
        count=np.zeros((nh, nu), dtype=np.int64),
    )


def build_surface_evidence(
    cir: CIR,
    capture_dir: Path,
    cfg: Config,
    tmp_dir: Path,
    *,
    floor_y: float = 0.0,
) -> tuple[dict[str, SurfaceGrid], dict[str, object]]:
    """Project sampled frames onto wall surfaces; returns (grids, info).

    ``info`` records frames used, points projected, per-surface sample counts and
    any warning, so ``damage.json`` is self-describing even when nothing fires.
    """
    info: dict[str, object] = {
        "frames_sampled": 0,
        "frames_with_rgb": 0,
        "points_projected": 0,
        "surfaces": {},
        "warnings": [],
    }
    walls = _wall_surfaces(cir.surfaces)
    if not walls:
        info["warnings"] = ["no wall surfaces with planes - damage evidence skipped"]
        return {}, info
    if not cfg.damage.enabled:
        info["warnings"] = ["damage assessment disabled by config"]
        return {}, info

    grids = {s.id: _empty_grid(s, cfg, floor_y) for s in walls}
    d = cfg.damage
    stride = max(1, d.frame_stride)

    frame_by_idx = {f.idx: f for f in cir.frames if f.pose is not None and f.K is not None}
    sampled = sorted(i for i in frame_by_idx if i % stride == 0)[: d.max_frames]
    info["frames_sampled"] = len(sampled)
    if not sampled:
        info["warnings"] = ["no posed frames with intrinsics - damage evidence skipped"]
        return grids, info

    # One RGB decode pass; scaled to the depth grid so pixel (v, u) is shared.
    first = frame_by_idx[sampled[0]]
    depth0 = read_depth_m(capture_dir / str(first.depth_ref), cfg.depth_scale_m)
    if depth0 is None:
        info["warnings"] = ["no depth images on disk - damage evidence skipped"]
        return grids, info
    h_px, w_px = depth0.shape
    rgb_by_idx = extract_rgb_frames(
        capture_dir / "rgb.mp4", sampled, (h_px, w_px), tmp_dir, stride=stride
    )
    info["frames_with_rgb"] = len(rgb_by_idx)

    s_planes = [
        (grids[s.id], np.array([s.plane.normal[0], s.plane.normal[2]]), float(s.plane.d))
        for s in walls
        if s.plane is not None
    ]
    n_proj = 0
    for idx in sampled:
        frame = frame_by_idx[idx]
        depth = read_depth_m(capture_dir / str(frame.depth_ref), cfg.depth_scale_m)
        rgb = rgb_by_idx.get(idx)
        if depth is None or rgb is None or depth.shape != rgb.shape[:2]:
            continue
        conf = read_confidence(capture_dir / str(frame.conf_ref)) if frame.conf_ref else None
        valid = (depth >= d.min_depth_m) & (depth <= d.max_depth_m)
        if conf is not None and conf.shape == depth.shape:
            valid &= conf >= d.confidence_min
        if not valid.any():
            continue
        n_proj += _accumulate(frame, depth, rgb, valid, s_planes, d.surface_tol_m)
    info["points_projected"] = n_proj
    info["surfaces"] = {
        gid: {
            "room_id": g.room_id,
            "length_m": round(g.length_m, 4),
            "cells": int((g.count > 0).sum()),
            "samples": int(g.count.sum()),
        }
        for gid, g in grids.items()
    }
    if n_proj == 0:
        info["warnings"] = ["no points projected onto wall surfaces (thin evidence)"]
    return grids, info


def _accumulate(
    frame: object,
    depth: NDArray[np.float64],
    rgb: NDArray[np.uint8],
    valid: NDArray[np.bool_],
    s_planes: list[tuple[SurfaceGrid, NDArray[np.float64], float]],
    tol_m: float,
) -> int:
    """Back-project one frame's valid pixels and accumulate them onto surfaces.

    Returns the number of points that landed on a surface. A point is assigned to
    the **nearest** wall plane (within ``tol_m``, inside its span and height band)
    so corner points are not double-counted.
    """
    vv, uu = np.nonzero(valid)
    zc = depth[vv, uu]
    K = np.array(frame.K, dtype=np.float64).reshape(3, 3)  # type: ignore[attr-defined]
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    if abs(fx) < 1e-9 or abs(fy) < 1e-9:
        return 0
    xc = (uu - cx) * zc / fx
    yc = (vv - cy) * zc / fy
    pose = np.array(frame.pose, dtype=np.float64).reshape(4, 4)  # type: ignore[attr-defined]
    world = (pose[:3, :3] @ np.stack([xc, yc, zc], axis=1).T).T + pose[:3, 3]
    wx, wy, wz = world[:, 0], world[:, 1], world[:, 2]
    cols = rgb[vv, uu].astype(np.float64)

    best_dist = np.full(wx.shape, np.inf)
    best_si = np.full(wx.shape, -1, dtype=np.int64)
    for si, (g, n_xz, off) in enumerate(s_planes):
        signed = np.abs(n_xz[0] * wx + n_xz[1] * wz + off)
        cand = signed <= tol_m
        if not cand.any():
            continue
        s_coord = (wx - g.a_xz[0]) * g.tangent[0] + (wz - g.a_xz[1]) * g.tangent[1]
        cand &= (s_coord >= 0.0) & (s_coord <= g.length_m)
        cand &= (wy >= g.h0) & (wy <= g.h1)
        upd = cand & (signed < best_dist)
        best_dist[upd] = signed[upd]
        best_si[upd] = si

    placed = 0
    for si, (g, _n, _o) in enumerate(s_planes):
        sel = best_si == si
        if not sel.any():
            continue
        s_coord = (wx[sel] - g.a_xz[0]) * g.tangent[0] + (wz[sel] - g.a_xz[1]) * g.tangent[1]
        hgt = wy[sel] - g.h0
        iu = np.floor(s_coord / g.cell_m).astype(np.int64)
        ih = np.floor(hgt / g.cell_m).astype(np.int64)
        ok = (iu >= 0) & (iu < g.count.shape[1]) & (ih >= 0) & (ih < g.count.shape[0])
        iu, ih = iu[ok], ih[ok]
        np.add.at(g.rgb_sum, (ih, iu), cols[sel][ok])
        np.add.at(g.count, (ih, iu), 1)
        placed += int(ok.sum())
    return placed
