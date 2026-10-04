"""Region proposal + classification on surface colour evidence (plan 04e s1-s2).

Deterministic, disclosed colour heuristics over the per-surface ``(height,
along-wall)`` grid produced by :mod:`scan2plan.damage.evidence`:

- ``mold``        dark, desaturated clusters (low luminance, low saturation);
- ``water_stain`` yellow/brown tint (R - B high) below a brightness cap;
- ``crack``       thin, elongated high-gradient runs;
- ``paint_peel``  fragmented high-gradient patches (not crack-like).

Masks are resolved by priority (mold > water_stain > crack > paint_peel) so a
cell is claimed by one class only, then clustered with 8-connectivity. Every
region carries a metric extent and an axis-aligned polygon in the surface frame
(``along-wall`` metres, ``height above floor`` metres). ``spalling``/``rot`` stay
in the published taxonomy but require the disclosed SAM/CLIP model hook.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage

from scan2plan.cir import Damage, DamageClass, Extent
from scan2plan.config import Config
from scan2plan.damage.evidence import SurfaceGrid
from scan2plan.util.logging import get_logger

logger = get_logger("scan2plan.damage.detect")

#: Emission order - fixes the (deterministic) ordering of ids.
CLASS_ORDER: tuple[DamageClass, ...] = ("mold", "water_stain", "crack", "paint_peel")


def _edge_magnitude(lum: NDArray[np.float64]) -> NDArray[np.float64]:
    """Per-cell max absolute luminance difference to a 4-neighbour.

    A central-difference gradient halves the response at a thin (1-2 cell) line
    and misses it; the max-neighbour difference marks both sides of a thin edge,
    which is what a crack looks like on a wall.
    """
    grad = np.zeros_like(lum)
    if lum.shape[0] >= 2:
        d = np.abs(np.diff(lum, axis=0))
        grad[:-1, :] = np.maximum(grad[:-1, :], d)
        grad[1:, :] = np.maximum(grad[1:, :], d)
    if lum.shape[1] >= 2:
        d = np.abs(np.diff(lum, axis=1))
        grad[:, :-1] = np.maximum(grad[:, :-1], d)
        grad[:, 1:] = np.maximum(grad[:, 1:], d)
    return grad


def _masks(grid: SurfaceGrid, cfg: Config) -> dict[str, NDArray[np.bool_]]:
    """Boolean per-class masks over the grid, priority-resolved."""
    d = cfg.damage
    rgb = grid.mean_rgb(d.min_cell_count)
    valid = ~np.isnan(rgb[..., 0])
    if not valid.any():
        return {}
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    # Masked max/min (invalid cells carry NaN, which would warn in nanmax/nanmin).
    mx = np.where(valid[..., None], rgb, 0.0).max(axis=2)
    mn = np.where(valid[..., None], rgb, 255.0).min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1.0)

    fill = float(np.nanmean(lum))
    lum_f = np.where(valid, lum, fill)
    grad = _edge_magnitude(lum_f)

    mold = valid & (lum < d.mold_max_lum) & (sat < d.mold_max_sat)
    stain = valid & ((r - b) > d.stain_min_rb) & (lum < d.stain_max_lum) & ~mold
    crack = valid & (grad > d.crack_min_grad) & ~mold & ~stain
    peel = valid & (grad > d.peel_min_grad) & ~mold & ~stain & ~crack
    return {"mold": mold, "water_stain": stain, "crack": crack, "paint_peel": peel}


def _region_polygon(grid: SurfaceGrid, r0: int, r1: int, c0: int, c1: int) -> list[list[float]]:
    """Axis-aligned rectangle (along-wall, height-above-floor) for a cell span."""
    s0, s1 = c0 * grid.cell_m, (c1 + 1) * grid.cell_m
    h0 = grid.h0 + r0 * grid.cell_m - grid.floor_y
    h1 = grid.h0 + (r1 + 1) * grid.cell_m - grid.floor_y
    return [
        [round(s0, 4), round(h0, 4)],
        [round(s1, 4), round(h0, 4)],
        [round(s1, 4), round(h1, 4)],
        [round(s0, 4), round(h1, 4)],
    ]


def detect_damages(
    grids: dict[str, SurfaceGrid],
    cfg: Config,
    *,
    evidence_ref: str = "damage.json",
) -> list[Damage]:
    """Detect damage regions across all surfaces; returns a deterministic list."""
    d = cfg.damage
    out: list[Damage] = []
    structure = np.ones((3, 3), dtype=int)
    for gid in sorted(grids):
        grid = grids[gid]
        masks = _masks(grid, cfg)
        for cls in CLASS_ORDER:
            mask = masks.get(cls)
            if mask is None or not mask.any():
                continue
            labels, n = ndimage.label(mask, structure=structure)
            comps = []
            for i in range(1, n + 1):
                rows, cols = np.nonzero(labels == i)
                if rows.size == 0:
                    continue
                r0, r1 = int(rows.min()), int(rows.max())
                c0, c1 = int(cols.min()), int(cols.max())
                cells = int(rows.size)
                area = cells * grid.cell_m * grid.cell_m
                bw = (c1 - c0 + 1) * grid.cell_m
                bh = (r1 - r0 + 1) * grid.cell_m
                if cells < d.min_region_cells:
                    continue
                if cls == "crack":
                    length = max(bw, bh)
                    aspect = length / max(min(bw, bh), 1e-6)
                    if length < d.crack_min_length_m or aspect < d.crack_min_aspect:
                        continue
                elif area < d.min_region_area_m2:
                    continue
                comps.append((r0, c0, r1, c1, area, bw, bh))
            comps.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
            for k, (r0, c0, r1, c1, area, bw, bh) in enumerate(comps, start=1):
                out.append(
                    Damage(
                        id=f"dmg_{gid}_{cls}_{k:02d}",
                        surface_id=gid,
                        cls=cls,
                        polygon=_region_polygon(grid, r0, r1, c0, c1),
                        extent=Extent(area_m2=round(area, 4), bbox_m=[round(bw, 4), round(bh, 4)]),
                        evidence_ref=evidence_ref,
                        confidence=d.confidence,
                    )
                )
    return out
