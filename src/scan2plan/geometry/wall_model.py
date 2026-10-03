"""Robust wall-line fitting, ported from ``room_fit.py`` (plan 04i).

This is the *logic* of the reference tool re-expressed natively so it runs with
our config thresholds and CIR conventions. Six ideas (04i section "what room_fit
does"):

1. Height-bin support: keep XZ cells occupied in many height bins -> vertical
   surfaces only (furniture/ghosts dropped).
2. Manhattan angle by histogram sharpness (walls are lines, not extents).
3. Per side, pick the NEAREST wall line beyond the camera path that also passes a
   run-length test -> rejects fridges/pillars and beats mirror ghosts, because the
   camera was inside the room.
4. Coverage, not guessing: unobserved sides are reported as None.
5. Seeded bootstrap over wall cells -> position/length/area intervals.
6. Warnings carry every caveat (too few cells, unobserved, weak coverage).

Pure numpy; deterministic given ``seed``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class WallParams:
    """The room_fit thresholds, injected from config (plan 04i / I4 ``outline``)."""

    cell_m: float = 0.02
    height_bins: int = 10
    min_height_bins: int = 4
    peak_smooth: int = 5
    min_peak_frac: float = 0.15
    cam_margin_m: float = 0.10
    min_run_m: float = 1.2
    run_gap_m: float = 0.10
    wall_min_m: float = 0.25
    wall_max_m: float = 1.9
    rng_seed: int = 1337


def wall_cells(
    pts: NDArray[np.float64],
    floor_y: float,
    ceil_y: float | None,
    p: WallParams | None = None,
) -> NDArray[np.float64]:
    """XZ cell centres (M,2) occupied in >= ``min_height_bins`` height bins.

    Only the wall band (floor+``wall_min_m`` .. min(ceiling-0.25, floor+``wall_max_m``))
    is used, so skirting and the ceiling join do not dilute the support test.
    """
    p = p or WallParams()
    if pts.size == 0:
        return np.zeros((0, 2))
    y_lo = floor_y + p.wall_min_m
    y_hi = (ceil_y - 0.25) if ceil_y is not None else floor_y + p.wall_max_m
    band = pts[(pts[:, 1] > y_lo) & (pts[:, 1] < y_hi)]
    if len(band) == 0:
        return np.zeros((0, 2))

    ix_raw = np.floor(band[:, 0] / p.cell_m).astype(np.int64)
    iz_raw = np.floor(band[:, 2] / p.cell_m).astype(np.int64)
    hb = np.clip(
        ((band[:, 1] - y_lo) / (y_hi - y_lo) * p.height_bins).astype(np.int64),
        0,
        p.height_bins - 1,
    )
    x0, z0 = int(ix_raw.min()), int(iz_raw.min())
    ix = ix_raw - x0
    iz = iz_raw - z0
    stride = int(iz.max()) + 1
    cid = ix * stride + iz
    # distinct (cell, height-bin) pairs -> count height bins per cell
    pair = np.unique(cid * p.height_bins + hb)
    cells, counts = np.unique(pair // p.height_bins, return_counts=True)
    keep = cells[counts >= p.min_height_bins]
    cx = ((keep // stride) + x0 + 0.5) * p.cell_m
    cz = ((keep % stride) + z0 + 0.5) * p.cell_m
    return np.stack([cx, cz], axis=1)


def rotate_xz(xz: NDArray[np.float64], theta: float) -> NDArray[np.float64]:
    """Rotate XZ by ``theta`` (room_fit ``_rot`` convention)."""
    c, s = float(np.cos(theta)), float(np.sin(theta))
    return np.stack([xz[:, 0] * c + xz[:, 1] * s, -xz[:, 0] * s + xz[:, 1] * c], axis=1)


def manhattan_angle(cells: NDArray[np.float64], step_deg: float = 0.5) -> float:
    """Angle (rad) where wall points pile up into the sharpest 1-D histograms."""
    if cells.size == 0:
        return 0.0
    best, best_t = -1.0, 0.0
    for deg in np.arange(0.0, 90.0, step_deg):
        uv = rotate_xz(cells, float(np.deg2rad(deg)))
        score = 0.0
        for k in (0, 1):
            v = uv[:, k]
            h, _ = np.histogram(v, bins=np.arange(v.min(), v.max() + 0.05, 0.05))
            score += float((h.astype(np.float64) ** 2).sum())
        if score > best:
            best, best_t = score, float(deg)
    return float(np.deg2rad(best_t))


def longest_run(coord: NDArray[np.float64], *, step: float = 0.05, max_gap: float = 0.10) -> float:
    """Longest stretch (m) of occupied ``step`` bins, tolerating gaps <= ``max_gap``."""
    if len(coord) == 0:
        return 0.0
    bins = np.arange(coord.min(), coord.max() + step, step)
    h, _ = np.histogram(coord, bins=bins)
    occ = np.flatnonzero(h > 0)
    if len(occ) == 0:
        return 0.0
    gap_bins = int(round(max_gap / step))
    best_len = 0.0
    start = prev = int(occ[0])
    for i in occ[1:]:
        i = int(i)
        if i - prev > gap_bins + 1:
            best_len = max(best_len, (prev - start + 1) * step)
            start = i
        prev = i
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


def _refine(vals: NDArray[np.float64], pos: float, half: float = 0.05) -> float:
    near = vals[np.abs(vals - pos) < half]
    return float(np.median(near)) if len(near) else float(pos)


def pick_wall_line(
    uv: NDArray[np.float64],
    axis: int,
    cam_lo: float,
    cam_hi: float,
    side: int,
    p: WallParams,
) -> float | None:
    """Nearest well-supported LONG wall line beyond the camera path (room_fit §5)."""
    vals = uv[:, axis]
    other = uv[:, 1 - axis]
    lo, hi = float(vals.min()) - 0.1, float(vals.max()) + 0.1
    h, edges = _hist1d(vals, lo, hi, cell=p.cell_m, smooth=p.peak_smooth)
    centres = (edges[:-1] + edges[1:]) / 2
    pk = _peaks(h)
    if len(pk) == 0:
        return None
    strongest = h[pk].max()
    cand = [int(i) for i in pk if h[i] >= p.min_peak_frac * strongest]
    if side > 0:
        cand = [i for i in cand if centres[i] > cam_hi + p.cam_margin_m]
        cand.sort(key=lambda i: centres[i])  # nearest first
    else:
        cand = [i for i in cand if centres[i] < cam_lo - p.cam_margin_m]
        cand.sort(key=lambda i: -centres[i])  # nearest first
    for i in cand:
        pos = _refine(vals, float(centres[i]))
        near = other[np.abs(vals - pos) < 0.06]
        if longest_run(near, max_gap=p.run_gap_m) >= p.min_run_m:  # length test
            return pos
    return None


def find_walls(
    uv: NDArray[np.float64], cam_uv: NDArray[np.float64], p: WallParams
) -> dict[str, float | None]:
    """Fit the 4 side lines (u_min/u_max along axis 0, v_min/v_max along axis 1)."""
    if len(uv) == 0 or len(cam_uv) == 0:
        return {"u_min": None, "u_max": None, "v_min": None, "v_max": None}
    cu0, cu1 = float(cam_uv[:, 0].min()), float(cam_uv[:, 0].max())
    cv0, cv1 = float(cam_uv[:, 1].min()), float(cam_uv[:, 1].max())
    return {
        "u_min": pick_wall_line(uv, 0, cu0, cu1, -1, p),
        "u_max": pick_wall_line(uv, 0, cu0, cu1, +1, p),
        "v_min": pick_wall_line(uv, 1, cv0, cv1, -1, p),
        "v_max": pick_wall_line(uv, 1, cv0, cv1, +1, p),
    }


def wall_coverage(
    uv: NDArray[np.float64], walls: dict[str, float | None], p: WallParams
) -> dict[str, float | None]:
    """Fraction of each wall span (between the perpendicular walls) with support."""
    if None in walls.values():
        return {k: None for k in walls}
    u0, u1 = walls["u_min"], walls["u_max"]
    v0, v1 = walls["v_min"], walls["v_max"]
    assert u0 is not None and u1 is not None and v0 is not None and v1 is not None
    out: dict[str, float | None] = {}
    sides = (
        ("u_min", 0, u0, (v0, v1)),
        ("u_max", 0, u1, (v0, v1)),
        ("v_min", 1, v0, (u0, u1)),
        ("v_max", 1, v1, (u0, u1)),
    )
    for name, axis, pos, (a0, a1) in sides:
        other = 1 - axis
        near = uv[np.abs(uv[:, axis] - pos) < 0.06]
        bins = np.arange(a0, a1 + 0.05, 0.05)
        if len(bins) < 2:
            out[name] = 0.0
            continue
        h, _ = np.histogram(near[:, other], bins=bins)
        out[name] = float((h > 0).mean())
    return out


def _ci(values: list[float]) -> tuple[float | None, float | None]:
    a = np.asarray(values, dtype=np.float64)
    if len(a) <= 10:
        return (None, None)
    return (float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)))


def fit_room(
    pts: NDArray[np.float64],
    cam_xyz: NDArray[np.float64],
    floor_y: float,
    ceil_y: float | None = None,
    *,
    params: WallParams | None = None,
    n_boot: int = 200,
    seed: int = 1337,
    min_coverage: float = 0.5,
) -> dict[str, object]:
    """Fit the 4 wall lines + bootstrap intervals (room_fit ``fit_room`` port).

    Returns ``walls_uv``, ``coverage``, ``width_m``/``depth_m``/``area_m2`` (each
    ``{"value","ci"}``), ``polygon_xz``, ``theta_deg``, ``n_wall_cells``, ``uv``
    (rotated cells, reused by stage 2) and ``warnings``.
    """
    params = params or WallParams()
    rng = np.random.default_rng(seed)
    cells = wall_cells(pts, floor_y, ceil_y, params)
    res: dict[str, object] = {"n_wall_cells": int(len(cells)), "warnings": []}
    warnings: list[str] = res["warnings"]  # type: ignore[assignment]
    res["params"] = {
        "cell_m": params.cell_m,
        "height_bins": params.height_bins,
        "min_height_bins": params.min_height_bins,
        "min_run_m": params.min_run_m,
        "run_gap_m": params.run_gap_m,
        "cam_margin_m": params.cam_margin_m,
        "min_peak_frac": params.min_peak_frac,
    }
    if len(cells) < 200:
        warnings.append("too few wall cells - capture unusable")
        res["uv"] = cells
        return res

    theta = manhattan_angle(cells)
    uv = rotate_xz(cells, theta)
    cam_uv = rotate_xz(cam_xyz[:, [0, 2]], theta)
    walls = find_walls(uv, cam_uv, params)
    cov = wall_coverage(uv, walls, params)
    res.update(theta_deg=float(np.rad2deg(theta)), walls_uv=walls, coverage=cov, uv=uv)

    missing = [k for k, v in walls.items() if v is None]
    if missing:
        warnings.append(f"walls not found (unobserved): {missing}")
        return res
    weak = [k for k, v in cov.items() if v is not None and v < min_coverage]
    if weak:
        warnings.append(
            f"weak wall coverage < {min_coverage:.0%}: {weak} - widen intervals / flag partial"
        )

    boot_pos: dict[str, list[float]] = {k: [] for k in walls}
    widths: list[float] = []
    areas: list[float] = []
    for _ in range(n_boot):
        sel = rng.integers(0, len(uv), len(uv))
        w = find_walls(uv[sel], cam_uv, params)
        if None in w.values():
            continue
        for k in w:
            assert w[k] is not None
            boot_pos[k].append(float(w[k]))
        width_b = float(w["u_max"]) - float(w["u_min"])  # type: ignore[arg-type]
        depth_b = float(w["v_max"]) - float(w["v_min"])  # type: ignore[arg-type]
        widths.append(width_b)
        areas.append(width_b * depth_b)

    u0, u1 = walls["u_min"], walls["u_max"]
    v0, v1 = walls["v_min"], walls["v_max"]
    assert u0 is not None and u1 is not None and v0 is not None and v1 is not None
    width = u1 - u0
    depth = v1 - v0
    res["width_m"] = {"value": float(width), "ci": _ci(widths)}
    res["depth_m"] = {
        "value": float(depth),
        "ci": _ci(
            [float(b) - float(a) for a, b in zip(boot_pos["v_max"], boot_pos["v_min"], strict=True)]
        ),
    }
    res["area_m2"] = {"value": float(width * depth), "ci": _ci(areas)}
    res["pos_ci"] = {k: _ci(v) for k, v in boot_pos.items()}
    res["bootstrap_note"] = (
        "Point-resampling CI only. Add odometry/scale error on top before reporting."
    )

    corners_uv = np.array([[u0, v0], [u1, v0], [u1, v1], [u0, v1]], dtype=np.float64)
    c, s = float(np.cos(theta)), float(np.sin(theta))
    res["polygon_xz"] = np.stack(
        [corners_uv[:, 0] * c - corners_uv[:, 1] * s, corners_uv[:, 0] * s + corners_uv[:, 1] * c],
        axis=1,
    ).tolist()
    return res


def synthetic_room(
    seed: int = 1, *, wardrobe: bool = False
) -> tuple[NDArray[np.float64], NDArray[np.float64], float, float, tuple[float, float]]:
    """room_fit ``_synthetic``: 4.0x3.2 room rotated 20 deg with traps.

    Traps: a mirror ghost 2 m behind the x=W wall, a low sofa, a 0.7 m-run tall
    fridge, far stray outliers, and (optionally) a 2.4 m near-ceiling wardrobe.
    """
    rng = np.random.default_rng(seed)
    w, d = 4.0, 3.2
    floor_y, ceil_y = -1.4, 1.1
    chunks: list[NDArray[np.float64]] = []

    def wall(p0: tuple[float, float], p1: tuple[float, float], door=None, n: int = 40000) -> None:
        t = rng.uniform(0, 1, n)
        length = float(np.linalg.norm(np.array(p1) - np.array(p0)))
        if door:
            t = t[~((t * length > door[0]) & (t * length < door[1]))]
        x = p0[0] + (p1[0] - p0[0]) * t
        z = p0[1] + (p1[1] - p0[1]) * t
        y = rng.uniform(floor_y, ceil_y, len(t))
        chunks.append(np.stack([x, y, z], 1) + rng.normal(0, 0.008, (len(t), 3)))

    wall((0, 0), (w, 0))
    wall((w, 0), (w, d), door=(1.0, 1.9))
    wall((w, d), (0, d))
    wall((0, d), (0, 0))
    t = rng.uniform(0, d, 15000)  # mirror ghost, partial height
    chunks.append(np.stack([np.full_like(t, w + 2.0), rng.uniform(-0.2, 0.6, len(t)), t], 1))
    sx = rng.uniform(0.3, 1.8, 15000)  # sofa, low only
    sz = rng.uniform(0.3, 1.0, 15000)
    chunks.append(np.stack([sx, rng.uniform(floor_y, floor_y + 0.8, len(sx)), sz], 1))
    fx = rng.uniform(2.6, 3.3, 20000)  # fridge: 0.7 m run, 1.8 m high
    fz = rng.uniform(d - 0.65, d, 20000)
    chunks.append(np.stack([fx, rng.uniform(floor_y, floor_y + 1.8, len(fx)), fz], 1))
    if wardrobe:  # 2.4 m near-ceiling wardrobe covering x=0 wall
        wz = rng.uniform(0.4, 2.8, 40000)
        wx = rng.uniform(0.0, 0.6, 40000)
        chunks.append(np.stack([wx, rng.uniform(floor_y, ceil_y - 0.1, len(wz)), wz], 1))
    chunks.append(rng.uniform([-3, -1, -3], [8, 1, 8], (500, 3)))

    pts = np.concatenate(chunks)
    k = np.linspace(0, 2 * np.pi, 200)
    cam = np.stack([2 + 1.0 * np.cos(k), np.zeros_like(k), 1.6 + 0.8 * np.sin(k)], 1)
    a = np.deg2rad(20)
    rot = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    return pts @ rot.T, cam @ rot.T, floor_y, ceil_y, (w, d)


def _main() -> None:  # pragma: no cover - manual self-test entry point
    import argparse

    ap = argparse.ArgumentParser(description="room_fit logic self-test (plan 04i)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--wardrobe", action="store_true")
    args = ap.parse_args()
    if not args.selftest:
        ap.print_help()
        return
    pts, cam, fy, cy, (w, d) = synthetic_room(wardrobe=args.wardrobe)
    band = pts[(pts[:, 1] > fy + 0.25) & (pts[:, 1] < cy - 0.25)]
    naive = float(np.ptp(band[:, 0]) * np.ptp(band[:, 2]))
    res = fit_room(pts, cam, fy, cy)
    print(f"truth        : {w:.2f} x {d:.2f} = {w * d:.2f} m2")
    print(f"naive bbox   : area ~ {naive:.1f} m2 (axis-aligned, includes ghosts)")
    width = res["width_m"]  # type: ignore[index]
    depth = res["depth_m"]  # type: ignore[index]
    area = res["area_m2"]  # type: ignore[index]
    print(f"fit_room     : {width['value']:.3f} x {depth['value']:.3f} = {area['value']:.2f} m2")
    print("  area 95% CI:", area["ci"])
    print("  angle deg  :", round(res["theta_deg"], 1), "(truth 20 or 70)")  # type: ignore[arg-type]
    cov = res["coverage"]
    cov_txt = {k: (round(v, 2) if v is not None else v) for k, v in cov.items()}  # type: ignore[union-attr]
    print("  coverage   :", cov_txt)
    print("  warnings   :", res["warnings"])


if __name__ == "__main__":  # pragma: no cover
    _main()
