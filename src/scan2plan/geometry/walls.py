"""Stage 2: deterministic wall reconstruction from stage-1 observed evidence (04i).

Stage 1 (frozen) emits pure observed layers - **wall cells** each carrying a
per-cell height-bin ``support`` count, **floor cells**, and the **camera path**.
Stage 2 is the first *derivation* stage: it turns those noisy cells into walls,
deterministically and without re-opening the frozen stage-1 contract.

Agreed boundary (plan 04i redefinition)
---------------------------------------
* **Input** is the frozen ``stage1_observed.json`` payload + ``Config`` - never the
  raw cloud. Stage 2 is a *pure function of stage 1*.
* **Output** is a sidecar (``stage2_walls.json``); it is not a frozen interface.
  There is **no** polygon, corner, opening or measurement here (those are stage 3).
* **Deterministic** - no RNG; the same artifact + config yields byte-identical
  JSON. Bootstrap intervals are deferred to stage 3 / uncertainty.
* **Never fails** - degenerate input yields empty walls + a warning.

Pipeline (port of the tested ``room_fit`` / ``wall_model`` primitives)
---------------------------------------------------------------------
1. **Support gate** - keep wall cells occupied in >= ``min_height_bins`` height
   bins. A real wall is a vertical surface seen at many heights; ghosts,
   furniture edges and door frames typically occupy one or two (on the seed
   ``c00a170fe1`` this drops ~58% of cells).
2. **Manhattan frame** - dominant orthogonal angle from histogram sharpness.
3. **Per side** - the nearest well-supported *long* line beyond the camera path
   (``cam_margin_m`` + ``min_run_m``/``run_gap_m``); the room_fit rule that
   rejects fridges/pillars and beats mirror ghosts.
4. **Wall segments** - clip each line to the room extent; report coverage/support.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from scan2plan.config import Config

#: Structural constants (not decision thresholds - those live in I4 ``outline``).
LINE_SLAB_M = 0.06  # half-width of the band counted as "on" a fitted line (m)
RUN_STEP_M = 0.05  # run-length histogram bin (m)
REFINE_HALF_M = 0.05  # radius of the median refinement around a peak (m)
ANGLE_STEP_DEG = 0.5  # Manhattan-angle search step (deg)
MIN_WALL_CELLS = 200  # below this the fit is meaningless (room_fit parity)
WEAK_COVERAGE_FRAC = 0.5  # below this a wall span is flagged weak (room_fit parity)

#: The four sides, in deterministic output order.
SIDES = ("u_min", "u_max", "v_min", "v_max")
#: side -> (axis index in uv, outward sign beyond the camera path).
_SIDE_SPEC = {"u_min": (0, -1), "u_max": (0, +1), "v_min": (1, -1), "v_max": (1, +1)}


@dataclass(frozen=True)
class WallParams:
    """The wall-fitting thresholds, injected from the I4 ``outline`` block."""

    cell_m: float
    height_bins: int
    min_height_bins: int
    peak_smooth: int
    min_peak_frac: float
    cam_margin_m: float
    min_run_m: float
    run_gap_m: float


def wall_params_from_config(cfg: Config) -> WallParams:
    """Build ``WallParams`` from the I4 ``outline`` block (single source of truth)."""
    o = cfg.outline
    return WallParams(
        cell_m=o.cell_m,
        height_bins=o.height_bins,
        min_height_bins=o.min_height_bins,
        peak_smooth=o.peak_smooth,
        min_peak_frac=o.min_peak_frac,
        cam_margin_m=o.cam_margin_m,
        min_run_m=o.min_run_m,
        run_gap_m=o.run_gap_m,
    )


# ---------------------------------------------------------------------------
# rotation helpers (room_fit ``_rot`` convention: uv = R(theta) . xz)
# ---------------------------------------------------------------------------
def rotate_xz(xz: NDArray[np.float64], theta: float) -> NDArray[np.float64]:
    """Rotate XZ into the Manhattan uv frame."""
    c, s = float(np.cos(theta)), float(np.sin(theta))
    return np.stack([xz[:, 0] * c + xz[:, 1] * s, -xz[:, 0] * s + xz[:, 1] * c], axis=1)


def _uv_to_world(u: float, v: float, theta: float) -> tuple[float, float]:
    """Inverse of :func:`rotate_xz` for a single uv point -> world (x, z)."""
    c, s = float(np.cos(theta)), float(np.sin(theta))
    return (u * c - v * s, u * s + v * c)


# ---------------------------------------------------------------------------
# Manhattan angle (histogram sharpness)
# ---------------------------------------------------------------------------
def manhattan_angle(cells: NDArray[np.float64], step_deg: float = ANGLE_STEP_DEG) -> float:
    """Angle (rad) where wall cells pile up into the sharpest 1-D histograms."""
    if cells.size == 0:
        return 0.0
    best, best_t = -1.0, 0.0
    for deg in np.arange(0.0, 90.0, step_deg):
        uv = rotate_xz(cells, float(np.deg2rad(deg)))
        score = 0.0
        for k in (0, 1):
            v = uv[:, k]
            bins = np.arange(float(v.min()), float(v.max()) + 0.05, 0.05)
            if len(bins) < 2:
                continue
            h, _ = np.histogram(v, bins=bins)
            score += float((h.astype(np.float64) ** 2).sum())
        if score > best:
            best, best_t = score, float(deg)
    return float(np.deg2rad(best_t))


# ---------------------------------------------------------------------------
# run-length and 1-D histogram primitives
# ---------------------------------------------------------------------------
def longest_run(
    coord: NDArray[np.float64], *, step: float = RUN_STEP_M, max_gap: float = 0.10
) -> float:
    """Longest stretch (m) of occupied ``step`` bins, tolerating gaps <= ``max_gap``."""
    if len(coord) == 0:
        return 0.0
    bins = np.arange(float(coord.min()), float(coord.max()) + step, step)
    if len(bins) < 2:
        return 0.0
    h, _ = np.histogram(coord, bins=bins)
    occ = np.flatnonzero(h > 0)
    if len(occ) == 0:
        return 0.0
    gap_bins = int(round(max_gap / step))
    best_len = 0.0
    start = prev = int(occ[0])
    for i in occ[1:]:
        idx = int(i)
        if idx - prev > gap_bins + 1:
            best_len = max(best_len, (prev - start + 1) * step)
            start = idx
        prev = idx
    return float(max(best_len, (prev - start + 1) * step))


def _hist1d(
    vals: NDArray[np.float64], lo: float, hi: float, *, cell: float, smooth: int
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    edges = np.arange(lo, hi + cell, cell)
    h, _ = np.histogram(vals, bins=edges)
    k = np.ones(smooth) / smooth
    return np.convolve(h.astype(np.float64), k, mode="same"), edges


def _peaks(h: NDArray[np.float64]) -> NDArray[np.int64]:
    idx = [i for i in range(1, len(h) - 1) if h[i] >= h[i - 1] and h[i] > h[i + 1] and h[i] > 0]
    return np.array(idx, dtype=np.int64)


def _refine(vals: NDArray[np.float64], pos: float, half: float = REFINE_HALF_M) -> float:
    near = vals[np.abs(vals - pos) < half]
    return float(np.median(near)) if len(near) else float(pos)


def pick_wall_line(
    uv: NDArray[np.float64],
    axis: int,
    cam_lo: float,
    cam_hi: float,
    side: int,
    p: WallParams,
) -> tuple[float, float, float] | None:
    """Nearest well-supported LONG wall line beyond the camera path (room_fit §5).

    Returns ``(pos, peak_strength, run_m)`` or ``None`` when no candidate line
    passes the peak + run-length tests.
    """
    vals = uv[:, axis]
    other = uv[:, 1 - axis]
    lo, hi = float(vals.min()) - 0.1, float(vals.max()) + 0.1
    h, edges = _hist1d(vals, lo, hi, cell=p.cell_m, smooth=p.peak_smooth)
    centres = (edges[:-1] + edges[1:]) / 2
    pk = _peaks(h)
    if len(pk) == 0:
        return None
    strongest = float(h[pk].max())
    if strongest <= 0.0:
        return None
    cand = [int(i) for i in pk if h[i] >= p.min_peak_frac * strongest]
    if side > 0:
        cand = [i for i in cand if centres[i] > cam_hi + p.cam_margin_m]
        cand.sort(key=lambda i: centres[i])  # nearest first
    else:
        cand = [i for i in cand if centres[i] < cam_lo - p.cam_margin_m]
        cand.sort(key=lambda i: -centres[i])  # nearest first
    for i in cand:
        pos = _refine(vals, float(centres[i]))
        near = other[np.abs(vals - pos) < LINE_SLAB_M]
        run = longest_run(near, max_gap=p.run_gap_m)
        if run >= p.min_run_m:  # length test
            return pos, float(h[i] / strongest), run
    return None


def find_walls(
    uv: NDArray[np.float64], cam_uv: NDArray[np.float64], p: WallParams
) -> dict[str, tuple[float, float, float] | None]:
    """Fit the four side lines (u_min/u_max along axis 0, v_min/v_max along axis 1)."""
    empty: dict[str, tuple[float, float, float] | None] = dict.fromkeys(SIDES, None)
    if len(uv) == 0 or len(cam_uv) == 0:
        return empty
    cu0, cu1 = float(cam_uv[:, 0].min()), float(cam_uv[:, 0].max())
    cv0, cv1 = float(cam_uv[:, 1].min()), float(cam_uv[:, 1].max())
    return {
        "u_min": pick_wall_line(uv, 0, cu0, cu1, -1, p),
        "u_max": pick_wall_line(uv, 0, cu0, cu1, +1, p),
        "v_min": pick_wall_line(uv, 1, cv0, cv1, -1, p),
        "v_max": pick_wall_line(uv, 1, cv0, cv1, +1, p),
    }


# ---------------------------------------------------------------------------
# support gate (stage-1 artifact -> kept / dropped cells)
# ---------------------------------------------------------------------------
def _support_gate(
    wall_cells: list, min_bins: int
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.int64]]:
    """Split stage-1 wall cells into kept (support >= ``min_bins``) and dropped."""
    if not wall_cells:
        empty = np.empty((0, 2), dtype=np.float64)
        return empty, empty.copy(), np.empty((0,), dtype=np.int64)
    xz = np.array([[float(c["x"]), float(c["z"])] for c in wall_cells], dtype=np.float64)
    sup = np.array([int(c.get("support", 1)) for c in wall_cells], dtype=np.int64)
    keep = sup >= min_bins
    return xz[keep], xz[~keep], sup


# ---------------------------------------------------------------------------
# wall segments
# ---------------------------------------------------------------------------
def _near_extent(uv: NDArray[np.float64], axis: int, pos: float) -> tuple[float, float]:
    """Extent (m) along the *other* axis of the cells sitting on this line."""
    near = uv[np.abs(uv[:, axis] - pos) < LINE_SLAB_M]
    other = near[:, 1 - axis]
    if len(other) == 0:
        return float(uv[:, 1 - axis].min()), float(uv[:, 1 - axis].max())
    return float(other.min()), float(other.max())


def _coverage_along(near: NDArray[np.float64], other_axis: int, s0: float, s1: float) -> float:
    """Fraction of the span [s0, s1] with at least one cell near the line."""
    if s1 <= s0:
        return 0.0
    bins = np.arange(s0, s1 + RUN_STEP_M, RUN_STEP_M)
    if len(bins) < 2:
        return 0.0
    h, _ = np.histogram(near[:, other_axis], bins=bins)
    return float((h > 0).mean())


def _wall_records(
    fit: dict[str, tuple[float, float, float] | None],
    uv: NDArray[np.float64],
    theta: float,
) -> list[dict[str, object]]:
    """Build the four wall records (line, span, length, coverage, support)."""
    u_lo = fit["u_min"][0] if fit["u_min"] is not None else None
    u_hi = fit["u_max"][0] if fit["u_max"] is not None else None
    v_lo = fit["v_min"][0] if fit["v_min"] is not None else None
    v_hi = fit["v_max"][0] if fit["v_max"] is not None else None
    recs: list[dict[str, object]] = []
    for side in SIDES:
        axis, _sign = _SIDE_SPEC[side]
        hit = fit[side]
        if hit is None:
            recs.append(
                {
                    "side": side,
                    "state": "unobserved",
                    "rule": "none_found",
                    "line_uv": None,
                    "line_world": None,
                    "length_m": 0.0,
                    "coverage": None,
                    "support": 0,
                    "run_m": 0.0,
                    "peak_strength": 0.0,
                }
            )
            continue
        pos, peak, run = hit
        # Span runs along the perpendicular axis; prefer the fitted perpendicular
        # lines, else fall back to the observed extent of the cells on this line.
        if axis == 0:
            span = (
                (v_lo, v_hi)
                if (v_lo is not None and v_hi is not None)
                else _near_extent(uv, axis, pos)
            )
        else:
            span = (
                (u_lo, u_hi)
                if (u_lo is not None and u_hi is not None)
                else _near_extent(uv, axis, pos)
            )
        s0, s1 = float(span[0]), float(span[1])
        if s1 < s0:
            s0, s1 = s1, s0
        length = float(s1 - s0)
        a_uv = (pos, s0) if axis == 0 else (s0, pos)
        b_uv = (pos, s1) if axis == 0 else (s1, pos)
        a_w = _uv_to_world(a_uv[0], a_uv[1], theta)
        b_w = _uv_to_world(b_uv[0], b_uv[1], theta)
        near = uv[np.abs(uv[:, axis] - pos) < LINE_SLAB_M]
        recs.append(
            {
                "side": side,
                "state": "observed",
                "rule": "nearest_supported_long_line_beyond_camera",
                "line_uv": {"axis": "u" if axis == 0 else "v", "pos": round(pos, 4)},
                "line_world": {
                    "a": [round(a_w[0], 4), round(a_w[1], 4)],
                    "b": [round(b_w[0], 4), round(b_w[1], 4)],
                },
                "length_m": round(length, 4),
                "coverage": round(_coverage_along(near, 1 - axis, s0, s1), 4),
                "support": int(near.shape[0]),
                "run_m": round(run, 4),
                "peak_strength": round(peak, 4),
            }
        )
    return recs


def _camera_inside_fraction(
    cam_uv: NDArray[np.float64],
    fit: dict[str, tuple[float, float, float] | None],
    uv: NDArray[np.float64],
) -> float | None:
    """Report-only: fraction of the camera path inside the fitted wall rectangle.

    Unobserved sides fall back to the kept-cell extent so the check still runs; the
    honest stage-3 assertion lives in the (future) closing stage.
    """
    if cam_uv.shape[0] == 0:
        return None
    u_lo = fit["u_min"][0] if fit["u_min"] is not None else float(uv[:, 0].min())
    u_hi = fit["u_max"][0] if fit["u_max"] is not None else float(uv[:, 0].max())
    v_lo = fit["v_min"][0] if fit["v_min"] is not None else float(uv[:, 1].min())
    v_hi = fit["v_max"][0] if fit["v_max"] is not None else float(uv[:, 1].max())
    inside = (
        (cam_uv[:, 0] >= u_lo)
        & (cam_uv[:, 0] <= u_hi)
        & (cam_uv[:, 1] >= v_lo)
        & (cam_uv[:, 1] <= v_hi)
    )
    return round(float(inside.mean()), 4)


def _extent_world(cells: NDArray[np.float64]) -> dict[str, list[float]] | None:
    """Bounding extents (m) of world-XZ cells."""
    if cells.shape[0] == 0:
        return None
    return {
        "x_m": [round(float(cells[:, 0].min()), 3), round(float(cells[:, 0].max()), 3)],
        "z_m": [round(float(cells[:, 1].min()), 3), round(float(cells[:, 1].max()), 3)],
    }


def _unobserved_wall(side: str) -> dict[str, object]:
    """A wall record for a side with no fitted line (honest, never guessed)."""
    return {
        "side": side,
        "state": "unobserved",
        "rule": "none_found",
        "line_uv": None,
        "line_world": None,
        "length_m": 0.0,
        "coverage": None,
        "support": 0,
        "run_m": 0.0,
        "peak_strength": 0.0,
    }


def reconstruct_walls(stage1: dict[str, object], cfg: Config) -> dict[str, object]:
    """Stage 2: reconstruct walls from the frozen stage-1 observed evidence (04i).

    Pure, deterministic function of ``stage1`` + ``cfg``: the support gate cleans
    the wall cells, the Manhattan frame aligns them, and each side is fit to the
    nearest well-supported long line beyond the camera path. Emits wall records
    only (no polygon/corners/openings). Never raises on degenerate input.
    """
    p = wall_params_from_config(cfg)
    warnings: list[str] = []

    layers = stage1.get("layers", {})
    assert isinstance(layers, dict)
    wall_cells = layers.get("wall_cells") or []
    floor_cells = layers.get("floor_cells") or []
    raw_cam = stage1.get("camera_xz") or []
    cam_xz = np.array([[float(a), float(b)] for a, b in raw_cam], dtype=np.float64)
    if cam_xz.size == 0:
        cam_xz = np.empty((0, 2), dtype=np.float64)

    counts = stage1.get("layer_counts", {})
    assert isinstance(counts, dict)
    n_input = int(counts.get("wall_cells", len(wall_cells)) or 0)
    if n_input > len(wall_cells):
        warnings.append("stage1_layer_capped: wall cells were subsampled by stage 1")

    kept, dropped, _sup = _support_gate(wall_cells, p.min_height_bins)
    cells = {
        "input": n_input,
        "kept": int(kept.shape[0]),
        "dropped": int(dropped.shape[0]),
        "dropped_reasons": {"support_below_min_height_bins": int(dropped.shape[0])},
    }

    theta = 0.0
    walls = [_unobserved_wall(side) for side in SIDES]
    cam_frac: float | None = None

    if kept.shape[0] < MIN_WALL_CELLS:
        warnings.append(
            f"too few wall cells ({kept.shape[0]} < {MIN_WALL_CELLS}) - wall fit skipped"
        )
    else:
        theta = manhattan_angle(kept)
        uv = rotate_xz(kept, theta)
        cam_uv = rotate_xz(cam_xz, theta) if cam_xz.shape[0] else cam_xz
        fit = find_walls(uv, cam_uv, p)
        walls = _wall_records(fit, uv, theta)
        cam_frac = _camera_inside_fraction(cam_uv, fit, uv)
        missing = [str(w["side"]) for w in walls if w["state"] == "unobserved"]
        if missing:
            warnings.append(f"walls not found (unobserved): {missing}")
        weak = [
            w["side"]
            for w in walls
            if w["coverage"] is not None and float(w["coverage"]) < WEAK_COVERAGE_FRAC
        ]
        if weak:
            warnings.append(f"weak wall coverage: {weak} - widen intervals / flag partial")

    floor_xz = (
        np.array([[float(a), float(b)] for a, b in floor_cells], dtype=np.float64)
        if floor_cells
        else np.empty((0, 2), dtype=np.float64)
    )

    return {
        "name": "wall reconstruction",
        "params": {
            "min_height_bins": p.min_height_bins,
            "cell_m": p.cell_m,
            "height_bins": p.height_bins,
            "peak_smooth": p.peak_smooth,
            "min_peak_frac": p.min_peak_frac,
            "cam_margin_m": p.cam_margin_m,
            "min_run_m": p.min_run_m,
            "run_gap_m": p.run_gap_m,
        },
        "manhattan_angle_deg": round(math.degrees(theta), 3),
        "cells": cells,
        "walls": walls,
        "extent_world": _extent_world(kept),
        "floor_extent_world": _extent_world(floor_xz),
        "camera_inside_walls_fraction": cam_frac,
        "warnings": warnings,
    }
