"""Stage-3 invariant checks (plan 04i fix loop, section 1).

Six invariants run after every capture; each prints its values and fails loudly
(``ok=False``) when violated, so a bad plan can never pass silently:

    no_overlap      total pairwise intersection area of room polygons == 0
                    (tolerance ``overlap_tol_m2``); every polygon must be simple.
    min_room        every room has area >= ``min_room_area_m2`` and an inscribed-
                    circle radius >= ``min_room_inradius_m``; smaller regions are
                    NOT rooms (merged into the neighbour sharing the longest
                    boundary, or labelled ``non_room_fragment``).
    coverage        share of camera-visited floor cells inside a room / opening /
                    unobserved_enclosed polygon >= ``coverage_min``.
    camera_inside   every camera position is inside a room, an opening or an
                    ``open_space``.
    render_clip     walls are drawn only as clipped segments of their graph edges;
                    no wall line extends beyond the node it ends at.
    ceiling_sanity  a ceiling is ``measured`` only with >= ``ceiling_min_cells``
                    cells covering >= ``ceiling_min_footprint_frac`` of the room
                    footprint and a height in ``[ceiling_height_low_m,
                    ceiling_height_high_m]``; otherwise ``unmeasured`` with the
                    prior interval.  Across-room spread > ``ceiling_spread_max_m``
                    flags ``inconsistent_ceiling``.

Pure geometry over the emitted payloads; deterministic (no RNG, no ordering
effects beyond the sorted, rounded output).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from numpy.typing import NDArray
from scipy import ndimage
from shapely.geometry import Polygon

from scan2plan.config import Config
from scan2plan.geometry.rooms import uv_to_world

#: An invariant whose subject does not exist (e.g. no rooms) is skipped, not passed.
SKIP: bool | None = None


@dataclass(frozen=True)
class Invariant:
    """One invariant result: name, pass/fail/skip, a one-line detail and raw values."""

    name: str
    ok: bool | None
    detail: str
    values: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _valid(poly: Polygon) -> tuple[Polygon, bool]:
    """Return (usable polygon, was_valid): bow-ties are repaired by buffer(0)."""
    if poly.is_valid:
        return poly, True
    return poly.buffer(0), False


def _polys(stage3: dict[str, object], key: str) -> dict[str, Polygon]:
    """Room / unobserved polygons (world XZ) from a stage-3 payload, valid-ified."""
    out: dict[str, Polygon] = {}
    for r in stage3.get(key) or []:  # type: ignore[union-attr]
        assert isinstance(r, dict)
        raw = r.get("polygon_world") or []
        if len(raw) >= 3:
            poly, _ = _valid(Polygon([[float(p[0]), float(p[1])] for p in raw]))
            if not poly.is_empty and poly.area > 0.0:
                out[str(r.get("id"))] = poly
    return out


def inscribed_radius(poly: Polygon) -> float:
    """Largest inscribed-circle radius (deterministic binary search, 20 steps)."""
    if poly.buffer(-1e-6).is_empty:
        return 0.0
    hi = 1.0
    while not poly.buffer(-hi).is_empty and hi < 64.0:
        hi *= 2.0
    lo = 0.0
    for _ in range(20):
        mid = (lo + hi) / 2.0
        if poly.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return lo


def _xz(payload: dict[str, object], key: str) -> NDArray[np.float64]:
    """An (N,2) XZ array from a stage-1 layer list of [x, z] pairs."""
    layers = payload.get("layers")
    assert isinstance(layers, dict)
    raw = layers.get(key) or []
    if not raw:
        return np.empty((0, 2), dtype=np.float64)
    return np.array([[float(p[0]), float(p[1])] for p in raw], dtype=np.float64)


def _contains(poly: Polygon, xz: NDArray[np.float64]) -> NDArray[np.bool_]:
    if xz.shape[0] == 0:
        return np.zeros(0, dtype=bool)
    return shapely.contains_xy(poly, xz[:, 0], xz[:, 1])


def _seg_dist(pt: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Point-to-segment distance (metres)."""
    ax, az = a
    bx, bz = b
    dx, dz = bx - ax, bz - az
    n2 = dx * dx + dz * dz
    t = 0.0 if n2 == 0.0 else max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - az) * dz) / n2))
    return math.hypot(pt[0] - (ax + t * dx), pt[1] - (az + t * dz))


def _openings_world(
    stage3: dict[str, object],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """World endpoints of every stage-3 opening segment (axis-aware uv -> world)."""
    theta = float(stage3.get("theta_rad") or 0.0)
    out: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for o in stage3.get("openings") or []:  # type: ignore[union-attr]
        assert isinstance(o, dict)
        axis = 0 if o.get("axis") == "u" else 1
        off, s, e = (
            float(o.get("offset_m", 0.0)),
            float(o.get("start_m", 0.0)),
            float(o.get("end_m", 0.0)),
        )
        pts = (off, s), (off, e) if axis == 0 else (s, off), (e, off)
        out.append(
            (uv_to_world(pts[0][0], pts[0][1], theta), uv_to_world(pts[1][0], pts[1][1], theta))
        )
    return out


def _open_spaces_world(
    stage2: dict[str, object],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    out: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for o in stage2.get("open_spaces") or []:  # type: ignore[union-attr]
        assert isinstance(o, dict)
        ep = o.get("endpoints_world") or {}
        a, b = ep.get("a"), ep.get("b")
        if a and b:
            out.append(((float(a[0]), float(a[1])), (float(b[0]), float(b[1]))))
    return out


# ---------------------------------------------------------------------------
# the six invariants
# ---------------------------------------------------------------------------
def _polys_raw(stage3: dict[str, object]) -> dict[str, Polygon]:
    """Room polygons WITHOUT valid-ification (so validity can be judged)."""
    out: dict[str, Polygon] = {}
    for r in stage3.get("rooms") or []:  # type: ignore[union-attr]
        assert isinstance(r, dict)
        raw = r.get("polygon_world") or []
        if len(raw) >= 3:
            out[str(r.get("id"))] = Polygon([[float(p[0]), float(p[1])] for p in raw])
    return out


def _footprint_frac(xz: NDArray[np.float64], room_area_m2: float, bin_m: float = 0.10) -> float:
    """Share of the room footprint covered by a point set (raster, closed + filled).

    A plane "covers" the footprint where its points sit; a light closing plus a
    hole fill merges sparse returns of the same solid surface into one patch.
    """
    if xz.shape[0] == 0 or room_area_m2 <= 0.0:
        return 0.0
    ix, iz = np.floor(xz / bin_m).astype(np.int64).T
    i0, j0 = int(ix.min()), int(iz.min())
    mask = np.zeros((int(ix.max()) - i0 + 1, int(iz.max()) - j0 + 1), dtype=bool)
    mask[ix - i0, iz - j0] = True
    mask = ndimage.binary_closing(mask, iterations=1)
    mask = ndimage.binary_fill_holes(mask)
    return float(mask.sum()) * bin_m * bin_m / room_area_m2


def _inv_no_overlap(stage3: dict[str, object], cfg: Config) -> Invariant:
    """Room polygons must be simple and pairwise non-overlapping."""
    raw = _polys_raw(stage3)
    polys: dict[str, Polygon] = {}
    invalid: list[str] = []
    for rid, p in raw.items():
        usable, was_valid = _valid(p)
        polys[rid] = usable
        if not was_valid:
            invalid.append(rid)
    pairs: list[dict[str, object]] = []
    total = 0.0
    ids = sorted(polys)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            inter = polys[a].intersection(polys[b])
            if inter.is_empty:
                continue
            area = float(inter.area)
            if area > 1e-9:
                total += area
                pairs.append({"rooms": [a, b], "overlap_m2": round(area, 6)})
    tol = cfg.outline.overlap_tol_m2
    ok = not invalid and total <= tol
    return Invariant(
        "no_overlap",
        ok,
        f"total pairwise overlap {total:.6f} m2 (tol {tol}) | invalid polygons {invalid or 'none'}",
        {"total_overlap_m2": round(total, 6), "overlaps": pairs, "invalid_polygons": invalid},
    )


def _inv_min_room(stage3: dict[str, object], cfg: Config) -> Invariant:
    """Every emitted room must clear the minimum-area and inradius gates."""
    o = cfg.outline
    rooms: list[dict[str, object]] = []
    bad: list[dict[str, object]] = []
    for rid, poly in _polys(stage3, "rooms").items():
        area = float(poly.area)
        r = round(inscribed_radius(poly), 4)
        rec: dict[str, object] = {"room": rid, "area_m2": round(area, 4), "inradius_m": r}
        rooms.append(rec)
        if area < o.min_room_area_m2 or r < o.min_room_inradius_m:
            bad.append(rec)
    return Invariant(
        "min_room",
        not bad,
        f"{len(rooms)} room(s); violations {bad or 'none'} "
        f"(min area {o.min_room_area_m2} m2, min inradius {o.min_room_inradius_m} m)",
        {"rooms": rooms, "violations": bad},
    )


def _inv_coverage(stage3: dict[str, object], stage1: dict[str, object], cfg: Config) -> Invariant:
    """Camera-visited floor cells must lie inside a room / opening / enclosed region."""
    cells = _xz(stage1, "camera_free_space")
    if cells.shape[0] == 0:
        return Invariant("coverage", SKIP, "no camera free-space cells", {"share": None})
    inside = np.zeros(cells.shape[0], dtype=bool)
    for poly in list(_polys(stage3, "rooms").values()) + list(
        _polys(stage3, "unobserved_enclosed").values()
    ):
        inside |= _contains(poly, cells)
    openings = _openings_world(stage3)
    rest_idx = np.flatnonzero(~inside)
    for a, b in openings:
        if rest_idx.size == 0:
            break
        near = np.array(
            [_seg_dist((float(cells[k, 0]), float(cells[k, 1])), a, b) <= 0.05 for k in rest_idx]
        )
        inside[rest_idx[near]] = True
        rest_idx = np.flatnonzero(~inside)
    share = float(inside.mean())
    return Invariant(
        "coverage",
        share >= cfg.outline.coverage_min,
        f"camera-visited cells inside a region: {share:.3f} (min {cfg.outline.coverage_min})",
        {"share": round(share, 4), "cells": int(cells.shape[0]), "outside": int((~inside).sum())},
    )


def _inv_camera_inside(
    stage3: dict[str, object], stage1: dict[str, object], stage2: dict[str, object]
) -> Invariant:
    """Every camera position must be inside a room, an opening or an open_space."""
    cam = stage1.get("camera_xz") or []
    if not cam:
        return Invariant("camera_inside", SKIP, "no camera path", {})
    xz = np.array([[float(p[0]), float(p[1])] for p in cam], dtype=np.float64)
    inside = np.zeros(xz.shape[0], dtype=bool)
    for poly in list(_polys(stage3, "rooms").values()) + list(
        _polys(stage3, "unobserved_enclosed").values()
    ):
        inside |= _contains(poly, xz)
    segments = _openings_world(stage3) + _open_spaces_world(stage2)
    for k in np.flatnonzero(~inside):
        p = (float(xz[k, 0]), float(xz[k, 1]))
        if any(_seg_dist(p, a, b) <= 0.10 for a, b in segments):
            inside[k] = True
    outside = [
        (round(float(xz[k, 0]), 3), round(float(xz[k, 1]), 3)) for k in np.flatnonzero(~inside)
    ]
    return Invariant(
        "camera_inside",
        not outside,
        f"{int(inside.sum())}/{xz.shape[0]} camera positions inside a room/opening/open_space",
        {"inside": int(inside.sum()), "total": int(xz.shape[0]), "outside_points": outside[:10]},
    )


def _inv_render_clip(stage2: dict[str, object], cfg: Config) -> Invariant:
    """Walls must be drawn clipped to their graph edges: no span beyond its end nodes."""
    segments = stage2.get("segments") or []
    graph = stage2.get("graph") or {}
    if not isinstance(graph, dict) or not segments or not graph.get("nodes"):
        return Invariant("render_clip", SKIP, "no wall segments/graph", {})
    node_tol = cfg.outline.node_tol_m
    node_merge = cfg.outline.node_merge_m
    nodes_uv = [(float(n["uv"][0]), float(n["uv"][1])) for n in graph.get("nodes", [])]  # type: ignore[union-attr]
    overshoot: list[dict[str, object]] = []
    total = 0.0
    for seg in segments:
        assert isinstance(seg, dict)
        axis = 0 if seg.get("axis") == "u" else 1
        off = float(seg.get("offset_m", 0.0))
        lo, hi = float(seg.get("start_m", 0.0)), float(seg.get("end_m", 0.0))
        perp = [u if axis == 0 else v for u, v in nodes_uv]
        along = [v if axis == 0 else u for u, v in nodes_uv]
        on = sorted(
            a
            for p, a in zip(perp, along, strict=True)
            if abs(p - off) <= node_tol and lo - node_merge <= a <= hi + node_merge
        )
        over = (hi - lo) if not on else max(0.0, on[0] - lo) + max(0.0, hi - on[-1])
        if over > node_merge + 1e-6:
            overshoot.append(
                {
                    "axis": seg.get("axis"),
                    "offset_m": off,
                    "span_m": [round(lo, 3), round(hi, 3)],
                    "nodes_m": [round(on[0], 3), round(on[-1], 3)] if on else None,
                    "overshoot_m": round(over, 4),
                }
            )
            total += over
    return Invariant(
        "render_clip",
        not overshoot,
        f"{len(overshoot)} wall segment(s) extend beyond their end nodes "
        f"(total {total:.2f} m; node merge tol {node_merge} m)",
        {"overshoot_segments": overshoot, "total_overshoot_m": round(total, 4)},
    )


def _inv_ceiling_sanity(
    stage3: dict[str, object],
    cfg: Config,
    *,
    points_xyz: NDArray[np.float64] | None = None,
    floor_y: float = 0.0,
) -> Invariant:
    """A measured ceiling needs enough cells, footprint coverage and a sane height."""
    o = cfg.outline
    rooms = stage3.get("rooms") or []
    if points_xyz is None or points_xyz.size == 0 or not rooms:
        return Invariant("ceiling_sanity", SKIP, "no rooms or no cloud", {})
    xz = points_xyz[:, [0, 2]]
    ys = points_xyz[:, 1]
    room_polys = _polys(stage3, "rooms")
    values: dict[str, object] = {"rooms": [], "floor_y": round(floor_y, 3)}
    bad: list[str] = []
    heights: list[float] = []
    room_list: list[object] = values["rooms"]  # type: ignore[assignment]
    for r in rooms:
        assert isinstance(r, dict)
        rid = str(r.get("id"))
        ceil = r.get("ceiling") or {}
        poly = room_polys.get(rid)
        if poly is None:
            continue
        in_room = _contains(poly, xz)
        above = in_room & (ys > floor_y + o.ceiling_min_above_floor_m)
        rec: dict[str, object] = {
            "room": rid,
            "reported": ceil.get("status"),
            "value": ceil.get("value"),
        }
        if ceil.get("status") == "measured":
            val = float(ceil.get("value") or 0.0)
            near = above & (np.abs(ys - (floor_y + val)) <= 0.05)
            area = float(poly.area)
            frac = _footprint_frac(xz[near], area)
            cells_ok = bool(near.sum() >= o.ceiling_min_cells)
            foot_ok = bool(frac >= o.ceiling_min_footprint_frac)
            height_ok = bool(o.ceiling_height_low_m <= val <= o.ceiling_height_high_m)
            rec |= {
                "cells": int(near.sum()),
                "cells_ok": cells_ok,
                "footprint_frac": round(frac, 4),
                "footprint_ok": foot_ok,
                "height_ok": height_ok,
            }
            if not (cells_ok and foot_ok and height_ok):
                bad.append(rid)
            heights.append(val)
        room_list.append(rec)
    spread = round(max(heights) - min(heights), 4) if len(heights) >= 2 else 0.0
    inconsistent = spread > o.ceiling_spread_max_m
    values["measured_heights"] = heights
    values["spread_m"] = spread
    values["inconsistent_ceiling"] = inconsistent
    return Invariant(
        "ceiling_sanity",
        not bad and not inconsistent,
        f"violating rooms {bad or 'none'} | measured heights {heights} spread {spread} m "
        f"(max {o.ceiling_spread_max_m}){' | inconsistent_ceiling' if inconsistent else ''}",
        values,
    )


def check_stage3_invariants(
    stage1: dict[str, object],
    stage2: dict[str, object],
    stage3: dict[str, object],
    cfg: Config,
    *,
    points_xyz: NDArray[np.float64] | None = None,
    floor_y: float = 0.0,
) -> list[Invariant]:
    """Run all six stage-3 invariants; skipped (``ok=None``) when no rooms exist."""
    if not (stage3.get("rooms") or []):
        note = "no rooms computed - invariants skipped"
        return [
            Invariant(n, SKIP, note, {})
            for n in ("no_overlap", "min_room", "coverage", "camera_inside", "ceiling_sanity")
        ] + [_inv_render_clip(stage2, cfg)]
    return [
        _inv_no_overlap(stage3, cfg),
        _inv_min_room(stage3, cfg),
        _inv_coverage(stage3, stage1, cfg),
        _inv_camera_inside(stage3, stage1, stage2),
        _inv_render_clip(stage2, cfg),
        _inv_ceiling_sanity(stage3, cfg, points_xyz=points_xyz, floor_y=floor_y),
    ]


def invariants_failed(invariants: list[Invariant]) -> list[Invariant]:
    """The failing invariants (skips never fail)."""
    return [i for i in invariants if i.ok is False]
