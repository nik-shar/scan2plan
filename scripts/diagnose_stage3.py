#!/usr/bin/env python3
"""Diagnose the stage-3 output of a capture (plan 04i fix-loop, section 2).

Reports, per capture (reads ``out/<cap>/{stage1_observed,stage2_walls,stage3_rooms}.json``
plus ``recon/points.npz``):

  1. pairwise room-polygon overlap areas (Shapely) + polygon validity,
  2. per-room area + inscribed-circle radius (min-room rule),
  3. per-room ceiling cell evidence: count, height histogram, chosen peak,
     footprint coverage, and the stage-1 global floor/ceiling reference,
  4. camera coverage: share of camera-visited cells inside a room / opening /
     unobserved_enclosed polygon; camera positions outside every polygon,
  5. every unobserved_enclosed region: area and whether the camera path enters it,
  6. wall render clipping: wall-segment span vs its graph nodes (overshoot).

Usage:
    python scripts/diagnose_stage3.py out [c00a170fe1 ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import Polygon

from scan2plan.geometry.planes import horizontal_planes

HIST_BIN_M = 0.05


def _load(root: Path, cap: str) -> tuple[dict, dict, dict, np.ndarray | None]:
    s1 = json.loads((root / cap / "stage1_observed.json").read_text())
    s2 = json.loads((root / cap / "stage2_walls.json").read_text())
    s3 = json.loads((root / cap / "stage3_rooms.json").read_text())
    pts_path = root / cap / "recon" / "points.npz"
    pts = np.load(pts_path)["points"].astype(np.float64) if pts_path.is_file() else None
    return s1, s2, s3, pts


def _polys_world(s3: dict, kind: str) -> list[tuple[str, list[list[float]]]]:
    out: list[tuple[str, list[list[float]]]] = []
    for r in s3.get(kind, []) or []:
        poly = r.get("polygon_world") or []
        if len(poly) >= 3:
            out.append((str(r.get("id")), [[float(p[0]), float(p[1])] for p in poly]))
    return out


def _inradius(poly: Polygon) -> float:
    """Largest inscribed-circle radius (binary search on negative buffer)."""
    lo, hi = 0.0, 1.0
    if poly.buffer(-1e-6).is_empty:
        return 0.0
    for _ in range(20):
        mid = (lo + hi) / 2.0
        if poly.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return lo


def _inside_mask(poly: Polygon, xz: np.ndarray) -> np.ndarray:
    """Vectorised point-in-polygon mask for an (N,2) xz array (boundary excluded)."""
    if xz.shape[0] == 0:
        return np.zeros(0, dtype=bool)
    return shapely.contains_xy(poly, xz[:, 0], xz[:, 1])


def diagnose(root: Path, cap: str) -> None:
    s1, s2, s3, pts = _load(root, cap)
    rooms = _polys_world(s3, "rooms")
    enclosed = _polys_world(s3, "unobserved_enclosed")
    print(f"\n================ {cap} ================")
    print(f"plan_score {s3.get('plan_score')} | rooms {len(rooms)} | enclosed {len(enclosed)}")

    # --- 1. overlap + validity --------------------------------------------
    polys = {rid: Polygon(p) for rid, p in rooms}
    fixed = {rid: (p if p.is_valid else p.buffer(0)) for rid, p in polys.items()}
    total_overlap = 0.0
    ids = sorted(polys)
    for i, a in enumerate(ids):
        pa = polys[a]
        if not pa.is_valid:
            print(
                f"  INVALID (self-intersecting) polygon: {a} "
                f"(make-valid area {fixed[a].area:.3f} m2)"
            )
        for b in ids[i + 1 :]:
            inter = fixed[a].intersection(fixed[b])
            area = float(inter.area) if not inter.is_empty else 0.0
            if area > 1e-9:
                total_overlap += area
                print(f"  OVERLAP {a} x {b}: {area:.4f} m2")
    print(f"  total pairwise room overlap: {total_overlap:.6f} m2")

    # --- 2. min-room rule ---------------------------------------------------
    for rid, p in rooms:
        poly = Polygon(p)
        if not poly.is_valid:
            poly = poly.buffer(0)
        print(
            f"  room {rid}: area {poly.area:.3f} m2 inradius {_inradius(poly):.3f} m verts {len(p)}"
        )

    # --- 3. ceiling evidence ------------------------------------------------
    floor_y = 0.0
    ceil_y = None
    if pts is not None and pts.size:
        planes = horizontal_planes(pts[:, 1])
        if planes:
            floor_y = planes[0].height_m
            ceil_y = planes[1].height_m if len(planes) > 1 else None
    ref = f"{'None' if ceil_y is None else f'{ceil_y - floor_y:.3f} m'}"
    print(f"  stage-1 global planes: floor {floor_y:+.3f} m, room height {ref}")
    if pts is not None:
        for r in s3.get("rooms", []) or []:
            rid = str(r["id"])
            poly = Polygon(r.get("polygon_world") or [])
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            inside = _inside_mask(poly, pts[:, [0, 2]])
            ys = pts[inside & (pts[:, 1] > floor_y + 2.0), 1]
            ceil = r["ceiling"]
            print(
                f"  ceiling {rid}: {ceil['value']} m "
                f"({ceil['status']}, support {ceil.get('support')})"
                f" | in-room points above floor+2m: {ys.size}"
            )
            if ys.size:
                hist, edges = np.histogram(
                    ys, bins=np.arange(ys.min(), ys.max() + HIST_BIN_M, HIST_BIN_M)
                )
                top = sorted(np.argsort(hist)[::-1][:6])
                print(
                    "    height histogram (above floor): "
                    + ", ".join(
                        f"{(edges[k] + edges[k + 1]) / 2 - floor_y:.2f}m:{hist[k]}pts" for k in top
                    )
                )
            val = float(ceil["value"])
            near = inside & (np.abs(pts[:, 1] - (floor_y + val)) <= 0.05)
            if near.any():
                bins = {(round(px / 0.02), round(pz / 0.02)) for px, pz in pts[near][:, [0, 2]]}
                print(
                    f"    cells near reported ceiling: {int(near.sum())} pts, footprint "
                    f"~{len(bins) * 0.02**2:.2f} m2 of {poly.area:.2f} m2"
                )

    # --- 4/5. coverage + unobserved regions ---------------------------------
    cam_pts = np.array(s1.get("camera_xz") or [], dtype=np.float64).reshape(-1, 2)
    free = np.array(
        (s1.get("layers") or {}).get("camera_free_space") or [], dtype=np.float64
    ).reshape(-1, 2)
    all_polys = []
    for _, p in rooms + enclosed:
        poly = Polygon(p)
        all_polys.append(poly if poly.is_valid else poly.buffer(0))
    for name, arr in (("camera path", cam_pts), ("free-space cells", free)):
        if arr.shape[0] == 0:
            continue
        hit = np.zeros(arr.shape[0], dtype=bool)
        for poly in all_polys:
            hit |= _inside_mask(poly, arr)
        print(f"  coverage ({name}): inside a room/enclosed polygon {hit.mean():.3f}")
    for e in s3.get("unobserved_enclosed") or []:
        poly = Polygon(e.get("polygon_world") or [])
        if not poly.is_valid:
            poly = poly.buffer(0)
        entered = bool(poly.area > 0 and _inside_mask(poly, cam_pts).any())
        free_in = int(_inside_mask(poly, free).sum()) if free.shape[0] else 0
        print(
            f"  unobserved {e.get('id')}: {poly.area:.2f} m2 ({e.get('cells')} cells)"
            f" | camera path enters {entered} | free-space cells inside {free_in}"
        )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0]) if args else Path("out")
    caps = args[1:] or ["c00a170fe1", "1a8384c3f6", "c7d28f72c6"]
    for cap in caps:
        diagnose(root, cap)
    return 0


if __name__ == "__main__":
    sys.exit(main())
