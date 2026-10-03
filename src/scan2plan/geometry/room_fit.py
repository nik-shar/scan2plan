"""room_fit.py - robust replacement for "oriented bounding box of the floor slab".

REFERENCE ONLY (plan 04i cleanup). This module is kept in the tree, **unused by
default**: stage 1 no longer calls it (see ``scan2plan.geometry.evidence``) and
stages 2/3 were archived to ``archive/old_stage23/`` for redesign. Import it
explicitly if you want to compare against the reference wall finder.

Why the bounding box fails
--------------------------
A bounding box encloses EVERY point. A few far returns (mirror ghosts, windows,
low-confidence depth) stretch it. It also always gives a rectangle, even when
the camera only saw part of the room.

What this does instead
----------------------
1. Keep only the "wall band" of the cloud (above furniture, below ceiling).
2. Project to the floor plane (X,Z; Y is up) into a 2 cm grid.
3. Keep cells that are occupied at MANY heights -> real vertical surfaces.
   (Sofas, floating noise and ghosts seen at one height are dropped.)
4. Find the Manhattan angle by maximising histogram sharpness.
5. For each of the 4 sides pick the NEAREST well-supported wall line that lies
   OUTSIDE the camera path. The camera was inside the room, so the real wall is
   the first strong line beyond it, not the farthest point.
6. Report wall coverage; a wall with little support is "unobserved", not guessed.
7. Bootstrap a confidence interval for each wall position.

Usage
-----
    from scan2plan.geometry.room_fit import fit_room
    res = fit_room(points_world, cam_xyz, floor_y=-1.474, ceil_y=None)
    print(res["area_m2"], res["walls"])

Self-test (no data needed):
    python -m scan2plan.geometry.room_fit --selftest
"""

from __future__ import annotations

import argparse

import numpy as np

CELL = 0.02  # grid cell size, metres
N_HBINS = 10  # height bins across the wall band
MIN_HBINS = 4  # a wall cell must be occupied in >= this many height bins
PEAK_SMOOTH = 5  # smoothing width (cells) for 1-D wall histograms
MIN_PEAK_FRAC = 0.15  # candidate wall must have >= this fraction of strongest peak
CAM_MARGIN = 0.10  # wall must be at least this far beyond camera path (m)


# --------------------------------------------------------------------------
# step 1-3: wall cells
# --------------------------------------------------------------------------
def wall_cells(pts, floor_y, ceil_y=None, cell=CELL, min_hbins=MIN_HBINS):
    """Return (M,2) array of XZ cell centres that look like vertical surfaces."""
    y_lo = floor_y + 0.25
    y_hi = (ceil_y - 0.25) if ceil_y is not None else floor_y + 1.9
    m = (pts[:, 1] > y_lo) & (pts[:, 1] < y_hi)
    p = pts[m]
    if len(p) == 0:
        return np.zeros((0, 2))
    ix = np.floor(p[:, 0] / cell).astype(np.int64)
    iz = np.floor(p[:, 2] / cell).astype(np.int64)
    hb = np.clip(
        ((p[:, 1] - y_lo) / (y_hi - y_lo) * N_HBINS).astype(np.int64), 0, N_HBINS - 1
    )
    ix -= ix.min()
    iz -= iz.min()
    stride = iz.max() + 1
    cid = ix * stride + iz
    # distinct (cell, height-bin) pairs, then count height bins per cell
    pair = np.unique(cid * N_HBINS + hb)
    cells, counts = np.unique(pair // N_HBINS, return_counts=True)
    keep = cells[counts >= min_hbins]
    # decode back to metres (undo the shifts)
    x0 = np.floor(p[:, 0] / cell).astype(np.int64).min()
    z0 = np.floor(p[:, 2] / cell).astype(np.int64).min()
    cx = ((keep // stride) + x0 + 0.5) * cell
    cz = ((keep % stride) + z0 + 0.5) * cell
    return np.stack([cx, cz], axis=1)


# --------------------------------------------------------------------------
# step 4: Manhattan angle
# --------------------------------------------------------------------------
def _rot(xz, theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.stack([xz[:, 0] * c + xz[:, 1] * s, -xz[:, 0] * s + xz[:, 1] * c], axis=1)


def manhattan_angle(cells, step_deg=0.5):
    """Angle (rad, 0..pi/2) where wall points pile up into sharp lines."""
    best, best_t = -1.0, 0.0
    for deg in np.arange(0, 90, step_deg):
        uv = _rot(cells, np.deg2rad(deg))
        score = 0.0
        for k in (0, 1):
            h, _ = np.histogram(
                uv[:, k], bins=np.arange(uv[:, k].min(), uv[:, k].max() + 0.05, 0.05)
            )
            score += float((h.astype(np.float64) ** 2).sum())
        if score > best:
            best, best_t = score, deg
    return np.deg2rad(best_t)


# --------------------------------------------------------------------------
# step 5: pick the four walls
# --------------------------------------------------------------------------
def _hist1d(vals, lo, hi, cell=CELL):
    edges = np.arange(lo, hi + cell, cell)
    h, _ = np.histogram(vals, bins=edges)
    k = np.ones(PEAK_SMOOTH) / PEAK_SMOOTH
    return np.convolve(h.astype(np.float64), k, mode="same"), edges


def _peaks(h):
    idx = [i for i in range(1, len(h) - 1) if h[i] >= h[i - 1] and h[i] > h[i + 1] and h[i] > 0]
    return np.array(idx, dtype=int)


def _refine(vals, pos, half=0.05):
    near = vals[np.abs(vals - pos) < half]
    return float(np.median(near)) if len(near) else pos


MIN_RUN = 1.2  # a wall line needs an unbroken run at least this long (m)
RUN_GAP = 0.10  # gaps up to this size do not break a run (m)


def _longest_run(coord, step=0.05, max_gap=RUN_GAP):
    """Longest stretch (m) of occupied 5 cm bins, tolerating small gaps."""
    if len(coord) == 0:
        return 0.0
    bins = np.arange(coord.min(), coord.max() + step, step)
    h, _ = np.histogram(coord, bins=bins)
    occ = np.flatnonzero(h > 0)
    if len(occ) == 0:
        return 0.0
    gap_bins = int(round(max_gap / step))
    best = cur_start = prev = occ[0]
    best_len = 0
    for i in occ:
        if i - prev > gap_bins + 1:  # gap too big: close the run
            best_len = max(best_len, (prev - cur_start + 1) * step)
            cur_start = i
        prev = i
    best_len = max(best_len, (prev - cur_start + 1) * step)
    return float(best_len)


def _pick_side(uv, axis, cam_lo, cam_hi, side):
    """Nearest wall line beyond the camera path that is also LONG."""
    vals = uv[:, axis]
    other = uv[:, 1 - axis]
    lo, hi = vals.min() - 0.1, vals.max() + 0.1
    h, edges = _hist1d(vals, lo, hi)
    centres = (edges[:-1] + edges[1:]) / 2
    pk = _peaks(h)
    if len(pk) == 0:
        return None
    strongest = h[pk].max()
    cand = [i for i in pk if h[i] >= MIN_PEAK_FRAC * strongest]
    if side > 0:
        cand = [i for i in cand if centres[i] > cam_hi + CAM_MARGIN]
        cand.sort(key=lambda i: centres[i])  # nearest first
    else:
        cand = [i for i in cand if centres[i] < cam_lo - CAM_MARGIN]
        cand.sort(key=lambda i: -centres[i])  # nearest first
    for i in cand:
        pos = _refine(vals, centres[i])
        near = other[np.abs(vals - pos) < 0.06]
        if _longest_run(near) >= MIN_RUN:  # LENGTH TEST
            return pos
    return None


def _find_walls(uv, cam_uv):
    cu0, cu1 = cam_uv[:, 0].min(), cam_uv[:, 0].max()
    cv0, cv1 = cam_uv[:, 1].min(), cam_uv[:, 1].max()
    return {
        "u_min": _pick_side(uv, 0, cu0, cu1, -1),
        "u_max": _pick_side(uv, 0, cu0, cu1, +1),
        "v_min": _pick_side(uv, 1, cv0, cv1, -1),
        "v_max": _pick_side(uv, 1, cv0, cv1, +1),
    }
def _coverage(uv, walls):
    """Fraction of each wall's length that has points near it (0..1)."""
    out = {}
    if None in walls.values():
        return {k: None for k in walls}
    u0, u1, v0, v1 = (walls["u_min"], walls["u_max"], walls["v_min"], walls["v_max"])
    for name, axis, pos, (a0, a1) in (
        ("u_min", 0, u0, (v0, v1)),
        ("u_max", 0, u1, (v0, v1)),
        ("v_min", 1, v0, (u0, u1)),
        ("v_max", 1, v1, (u0, u1)),
    ):
        other = 1 - axis
        near = uv[np.abs(uv[:, axis] - pos) < 0.06]
        bins = np.arange(a0, a1 + 0.05, 0.05)
        if len(bins) < 2:
            out[name] = 0.0
            continue
        h, _ = np.histogram(near[:, other], bins=bins)
        out[name] = float((h > 0).mean())
    return out


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------
def fit_room(pts, cam_xyz, floor_y, ceil_y=None, n_boot=200, seed=0, min_coverage=0.5):
    """Fit the four walls from a world point cloud.

    pts      (N,3) world points, Y up, metres
    cam_xyz  (K,3) camera centres in world frame, metres
    Returns dict with walls, polygon, area, intervals, coverage, warnings.
    """
    rng = np.random.default_rng(seed)
    cells = wall_cells(pts, floor_y, ceil_y)
    res = {"n_wall_cells": int(len(cells)), "warnings": []}
    if len(cells) < 200:
        res["warnings"].append("too few wall cells - capture unusable")
        return res

    theta = manhattan_angle(cells)
    uv = _rot(cells, theta)
    cam_uv = _rot(cam_xyz[:, [0, 2]], theta)
    walls = _find_walls(uv, cam_uv)
    cov = _coverage(uv, walls)
    res.update(theta_deg=float(np.rad2deg(theta)), walls_uv=walls, coverage=cov)

    missing = [k for k, v in walls.items() if v is None]
    if missing:
        res["warnings"].append(f"walls not found (unobserved): {missing}")
        return res
    weak = [k for k, v in cov.items() if v is not None and v < min_coverage]
    if weak:
        res["warnings"].append(
            f"weak wall coverage < {min_coverage:.0%}: {weak} "
            "- widen intervals / flag as partially observed"
        )

    # bootstrap confidence intervals
    boots = {k: [] for k in walls}
    wb, ab = [], []
    for _ in range(n_boot):
        sel = rng.integers(0, len(uv), len(uv))
        w = _find_walls(uv[sel], cam_uv)
        if None in w.values():
            continue
        for k in w:
            boots[k].append(w[k])
        wb.append(w["u_max"] - w["u_min"])
        ab.append((w["u_max"] - w["u_min"]) * (w["v_max"] - w["v_min"]))

    def ci(a):
        a = np.asarray(a)
        return (
            (float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)))
            if len(a) > 10
            else (None, None)
        )

    width = walls["u_max"] - walls["u_min"]
    depth = walls["v_max"] - walls["v_min"]
    res["width_m"] = {"value": float(width), "ci": ci(wb)}
    res["depth_m"] = {
        "value": float(depth),
        "ci": ci([b for b in (np.array(boots["v_max"]) - np.array(boots["v_min"]))]),
    }
    res["area_m2"] = {"value": float(width * depth), "ci": ci(ab)}
    res["bootstrap_note"] = (
        "Point-resampling CI only. Add odometry/scale error on top before reporting."
    )

    corners_uv = np.array(
        [
            [walls["u_min"], walls["v_min"]],
            [walls["u_max"], walls["v_min"]],
            [walls["u_max"], walls["v_max"]],
            [walls["u_min"], walls["v_max"]],
        ]
    )
    c, s = np.cos(theta), np.sin(theta)
    # inverse of _rot: x = u*c - v*s ; z = u*s + v*c
    res["polygon_xz"] = np.stack(
        [corners_uv[:, 0] * c - corners_uv[:, 1] * s, corners_uv[:, 0] * s + corners_uv[:, 1] * c],
        axis=1,
    ).tolist()
    res["uv_cells"] = uv
    return res


def debug_plot(res, cells_xz, cam_xyz, path="room_debug.png"):
    """Draw wall cells, camera path and fitted polygon. LOOK AT THIS."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(cells_xz[:, 0], cells_xz[:, 1], s=1, c="gray", label="wall cells")
    ax.plot(cam_xyz[:, 0], cam_xyz[:, 2], "b-", lw=1, label="camera path")
    if "polygon_xz" in res:
        poly = np.array(res["polygon_xz"] + [res["polygon_xz"][0]])
        ax.plot(poly[:, 0], poly[:, 1], "r-", lw=2, label="fitted room")
    ax.set_aspect("equal")
    ax.legend()
    ax.set_title("If the blue path leaves the red box, something is wrong")
    fig.savefig(path, dpi=110)
    return path
# --------------------------------------------------------------------------
# synthetic self-test: 4.0 x 3.2 m room rotated 20 deg, with traps
# --------------------------------------------------------------------------
def _synthetic(seed=1, wardrobe=False):
    rng = np.random.default_rng(seed)
    W, D = 4.0, 3.2
    floor_y, ceil_y = -1.4, 1.1
    pts = []

    def wall(p0, p1, door=None, n=40000):
        t = rng.uniform(0, 1, n)
        L = np.linalg.norm(np.array(p1) - np.array(p0))
        if door:
            ok = ~((t * L > door[0]) & (t * L < door[1]))
            t = t[ok]
        x = p0[0] + (p1[0] - p0[0]) * t
        z = p0[1] + (p1[1] - p0[1]) * t
        y = rng.uniform(floor_y, ceil_y, len(t))
        pts.append(np.stack([x, y, z], 1) + rng.normal(0, 0.008, (len(t), 3)))

    wall((0, 0), (W, 0))
    wall((W, 0), (W, D), door=(1.0, 1.9))  # 0.9 m door gap
    wall((W, D), (0, D))
    wall((0, D), (0, 0))
    # mirror ghost: a fake "wall" 2 m behind the x=W wall, partial height
    t = rng.uniform(0, D, 15000)
    pts.append(
        np.stack([np.full_like(t, W + 2.0), rng.uniform(-0.2, 0.6, len(t)), t], 1)
    )
    # sofa: block, low only
    sx = rng.uniform(0.3, 1.8, 15000)
    sz = rng.uniform(0.3, 1.0, 15000)
    pts.append(np.stack([sx, rng.uniform(floor_y, floor_y + 0.8, len(sx)), sz], 1))
    # fridge: 0.7 m wide, 0.65 m deep, 1.8 m TALL, against the z=D wall
    fx = rng.uniform(2.6, 3.3, 20000)
    fz = rng.uniform(D - 0.65, D, 20000)
    pts.append(np.stack([fx, rng.uniform(floor_y, floor_y + 1.8, len(fx)), fz], 1))
    if wardrobe:
        # 2.4 m wide, 0.6 m deep, nearly ceiling-high, covers most of the x=0 wall
        wz = rng.uniform(0.4, 2.8, 40000)
        wx = rng.uniform(0.0, 0.6, 40000)
        pts.append(np.stack([wx, rng.uniform(floor_y, ceil_y - 0.1, len(wz)), wz], 1))
    # far stray outliers
    pts.append(rng.uniform([-3, -1, -3], [8, 1, 8], (500, 3)))
    P = np.concatenate(pts)
    # camera path inside the room
    k = np.linspace(0, 2 * np.pi, 200)
    cam = np.stack([2 + 1.0 * np.cos(k), np.zeros_like(k), 1.6 + 0.8 * np.sin(k)], 1)
    # rotate whole scene 20 deg about Y axis
    a = np.deg2rad(20)
    R = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    return P @ R.T, cam @ R.T, floor_y, ceil_y, (W, D)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument(
        "--wardrobe", action="store_true", help="add a wide ceiling-high wardrobe (known hard case)"
    )
    a = ap.parse_args()
    if a.selftest:
        P, cam, fy, cy, (W, D) = _synthetic(wardrobe=a.wardrobe)
        # naive baseline: bounding box of everything in the wall band
        band = P[(P[:, 1] > fy + 0.25) & (P[:, 1] < cy - 0.25)]
        nb = np.ptp(band[:, 0]) * np.ptp(band[:, 2])
        r = fit_room(P, cam, fy, cy)
        print(f"truth        : {W:.2f} x {D:.2f} = {W * D:.2f} m2")
        print(f"naive bbox   : area ~ {nb:.1f} m2 (axis-aligned, includes ghosts)")
        print(
            f"fit_room     : {r['width_m']['value']:.3f} x "
            f"{r['depth_m']['value']:.3f} = {r['area_m2']['value']:.2f} m2"
        )
        print("  area 95% CI:", r["area_m2"]["ci"])
        print("  angle deg  :", round(r["theta_deg"], 1), "(truth 20 or 70)")
        print("  coverage   :", {k: round(v, 2) for k, v in r["coverage"].items()})
        print("  warnings   :", r["warnings"])