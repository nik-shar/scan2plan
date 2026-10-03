"""Three-stage room outline with explainable furniture removal (plan 04i).

Stage 1 (observed): outline of everything seen (furniture in, low-confidence/out-of-
range depth already dropped by S2). Stage 2 (classify): every region gets exactly one
label + the rule that fired (``noise_or_ghost`` / ``low_furniture`` /
``tall_furniture`` / ``suspected_occluder`` / ``wall``). Stage 3 (final): the wall
outline only, rectilinear, 4-8 edges, with per-wall state
(``observed`` / ``partially_occluded`` / ``unobserved``) and honest intervals
(bootstrap + odometry term in quadrature).

Wall finding is the ported ``wall_model`` logic; every threshold comes from config
(I4 ``outline``) so each stage JSON records the exact parameters that fired.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import Point, Polygon

from scan2plan.cir import Measurement, Opening, Plane, Room, Surface
from scan2plan.cir.measure import Tier
from scan2plan.config import Config
from scan2plan.geometry import wall_model as wm
from scan2plan.geometry.footprint import extract_footprint, merge_collinear, rotate2d

# Opening detector constants (structural, not decision thresholds).
DOOR_MIN_WIDTH_M = 0.55
DOOR_MAX_WIDTH_M = 1.6
WALL_SLAB_M = 0.08
DOOR_SCAN_HEIGHT_M = 2.2
MIN_WALL_LEN_M = 0.30
CEIL_CI_K = 3.0

LABELS = ("wall", "low_furniture", "tall_furniture", "suspected_occluder", "noise_or_ghost")


@dataclass
class Region:
    """One classified region: exactly one label + the rule that fired (§2)."""

    label: str
    rule: str
    params: dict[str, float | str]
    polygon_xz: list[list[float]]
    area_m2: float


@dataclass
class WallState:
    """Per-wall state for stage 3 (explainable)."""

    side: str  # u_min|u_max|v_min|v_max|step
    length_m: float
    state: str  # observed|partially_occluded|unobserved
    coverage: float | None
    occluder_rule: str | None = None


@dataclass
class OutlineResult:
    """Everything S3 produces: CIR entities + the three stage JSON payloads."""

    room: Room
    surfaces: list[Surface] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    measures: list[Measurement] = field(default_factory=list)
    stage1: dict[str, object] = field(default_factory=dict)
    stage2: dict[str, object] = field(default_factory=dict)
    stage3: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def wall_params_from_config(cfg: Config) -> wm.WallParams:
    """Build ``WallParams`` from the I4 ``outline`` block (single source of truth)."""
    o = cfg.outline
    return wm.WallParams(
        cell_m=o.cell_m,
        height_bins=o.height_bins,
        min_height_bins=o.min_height_bins,
        peak_smooth=o.peak_smooth,
        min_peak_frac=o.min_peak_frac,
        cam_margin_m=o.cam_margin_m,
        min_run_m=o.min_run_m,
        run_gap_m=o.run_gap_m,
        wall_min_m=o.wall_min_m,
        wall_max_m=o.wall_max_m,
        rng_seed=cfg.seed,
    )


def _measurement(
    id: str, kind: str, value: float, unit: str, half_width: float, method: str, tier: Tier
) -> Measurement:
    hw = max(abs(half_width), 1e-4)
    return Measurement(
        id=id,
        kind=kind,
        value=round(value, 4),
        unit=unit,
        ci_low=round(value - hw, 4),
        ci_high=round(value + hw, 4),
        method=method,
        tier=tier,
    )


def camera_travel_m(cam_xyz: NDArray[np.float64]) -> float:
    """Total path length of the camera centres (metres) - a plausibility signal."""
    if cam_xyz.shape[0] < 2:
        return 0.0
    d = np.diff(cam_xyz[:, [0, 2]], axis=0)
    return float(np.sum(np.hypot(d[:, 0], d[:, 1])))


def _grid_cells(
    xz: NDArray[np.float64], bin_m: float
) -> tuple[list[list[float]], set[tuple[int, int]]]:
    """Deduplicate XZ points to occupied grid cells: ([[cx,cz],...], {(ix,iz),...}).

    Pure binning - no hull, buffer, snapping or interpolation (plan 04i stage 1).
    """
    if xz.shape[0] == 0:
        return [], set()
    ix = np.floor(xz[:, 0] / bin_m).astype(np.int64)
    iz = np.floor(xz[:, 1] / bin_m).astype(np.int64)
    keys = set(zip(ix.tolist(), iz.tolist(), strict=True))
    cells = [[(i + 0.5) * bin_m, (j + 0.5) * bin_m] for i, j in sorted(keys)]
    return cells, keys


def _capped(cells: list, cap: int) -> list:
    """Deterministic subsample of a cell list to at most ``cap`` entries."""
    if len(cells) <= cap:
        return cells
    step = int(math.ceil(len(cells) / cap))
    return cells[::step]


def _carve_free_space(
    cam_xyz: NDArray[np.float64], points: NDArray[np.float64], bin_m: float, stride: int
) -> set[tuple[int, int]]:
    """Optional ray carve: mark free cells between the nearest camera and each point."""
    cam = cam_xyz[:, [0, 2]]
    if cam.shape[0] == 0 or points.shape[0] == 0:
        return set()
    tree = cKDTree(cam)
    pts = points[::stride]
    cells: set[tuple[int, int]] = set()
    for p in pts[:, [0, 2]]:
        _, i = tree.query(p)
        c0 = cam[int(i)]
        seg = p - c0
        length = float(np.hypot(seg[0], seg[1]))
        n = int(length / bin_m)
        for t in np.linspace(0.0, 1.0, n + 1):
            q = c0 + t * seg
            cells.add((int(math.floor(q[0] / bin_m)), int(math.floor(q[1] / bin_m))))
    return cells


def _keys_to_cells(keys: set[tuple[int, int]], bin_m: float) -> list[list[float]]:
    """Integer grid keys -> sorted cell centres ([[cx, cz], ...])."""
    return [[(i + 0.5) * bin_m, (j + 0.5) * bin_m] for i, j in sorted(keys)]


def _extent_m(keys: set[tuple[int, int]], bin_m: float) -> dict[str, list[float]] | None:
    """Bounding extents (metres) of a set of integer cells."""
    if not keys:
        return None
    arr = np.array(sorted(keys), dtype=np.float64) * bin_m
    return {
        "x_m": [round(float(arr[:, 0].min()), 3), round(float(arr[:, 0].max() + bin_m), 3)],
        "z_m": [round(float(arr[:, 1].min()), 3), round(float(arr[:, 1].max() + bin_m), 3)],
    }


def _evidence_stats(
    cam_xyz: NDArray[np.float64],
    floor_keys: set[tuple[int, int]],
    wall_keys: set[tuple[int, int]],
    bin_m: float,
) -> dict[str, object]:
    """Report-only statistics (never fail): camera inside evidence + extents (04i)."""
    cam = cam_xyz[:, [0, 2]]
    if cam.shape[0] == 0:
        return {"camera_inside_fraction": None}
    evidence = floor_keys | wall_keys
    neigh = [(dx, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)]
    cam_keys = {(int(math.floor(x / bin_m)), int(math.floor(z / bin_m))) for x, z in cam}
    if evidence:
        inside = sum(
            1 for k in cam_keys if any((k[0] + n[0], k[1] + n[1]) in evidence for n in neigh)
        )
        frac: float | None = inside / len(cam_keys)
    else:
        frac = 0.0
    ev_ext = _extent_m(evidence, bin_m)
    cam_ext = _extent_m(cam_keys, bin_m)
    exceeds: bool | None = None
    if ev_ext and cam_ext:
        exceeds = (
            cam_ext["x_m"][0] < ev_ext["x_m"][0] - bin_m
            or cam_ext["x_m"][1] > ev_ext["x_m"][1] + bin_m
            or cam_ext["z_m"][0] < ev_ext["z_m"][0] - bin_m
            or cam_ext["z_m"][1] > ev_ext["z_m"][1] + bin_m
        )
    return {
        "camera_inside_fraction": round(float(frac), 4) if frac is not None else None,
        "evidence_extent_m": ev_ext,
        "camera_extent_m": cam_ext,
        "camera_exceeds_evidence": exceeds,
    }


#: Cap on cells serialised per layer, so the evidence sidecar stays readable.
EVIDENCE_LAYER_CAP = 60000


def _evidence_layers(
    points: NDArray[np.float64],
    cam_xyz: NDArray[np.float64],
    floor_y: float,
    ceil_y: float | None,
    params: wm.WallParams,
    cfg: Config,
) -> tuple[
    list[dict[str, object]],
    list[list[float]],
    set[tuple[int, int]],
    set[tuple[int, int]],
    float,
]:
    """Wall cells (+support), floor cells, floor/wall integer keys and the bin (04i)."""
    o = cfg.outline
    bin_m = o.evidence_bin_m
    wcells, wcounts = wm.wall_cells_with_support(points, floor_y, ceil_y, params)
    wall_layer: list[dict[str, object]] = [
        {"x": round(float(cx), 3), "z": round(float(cz), 3), "support": int(s)}
        for (cx, cz), s in zip(wcells.tolist(), wcounts.tolist(), strict=True)
    ]
    wall_keys = {
        (int(math.floor(cx / bin_m)), int(math.floor(cz / bin_m))) for cx, cz in wcells.tolist()
    }
    slab = points[np.abs(points[:, 1] - floor_y) <= o.floor_band_m]
    floor_cells, floor_keys = _grid_cells(slab[:, [0, 2]], bin_m)
    return wall_layer, floor_cells, floor_keys, wall_keys, bin_m


def _camera_path_xz(cam_xyz: NDArray[np.float64], max_pts: int = 200) -> list[list[float]]:
    """Downsampled camera path (XZ) for the stage-1 evidence SVG."""
    if cam_xyz.shape[0] == 0:
        return []
    step = max(1, cam_xyz.shape[0] // max_pts)
    return [[float(a), float(b)] for a, b in cam_xyz[::step][:, [0, 2]]]


def observed_evidence(
    points: NDArray[np.float64],
    cam_xyz: NDArray[np.float64],
    floor_y: float,
    ceil_y: float | None,
    params: wm.WallParams,
    cfg: Config,
    points_unfiltered: NDArray[np.float64] | None = None,
) -> dict[str, object]:
    """Stage 1: pure observed evidence as layers - no hull/buffer/snap/interp (04i).

    Layers: wall cells (with per-cell support), floor cells, camera free-space
    (path, optionally ray-carved). Unknown stays blank. Reports statistics only
    (camera-inside fraction, extents) and never fails. An *unfiltered* layer
    (range/confidence gates off) is saved for comparison.
    """
    o = cfg.outline
    warnings: list[str] = []
    wall_layer, floor_cells, floor_keys, wall_keys, bin_m = _evidence_layers(
        points, cam_xyz, floor_y, ceil_y, params, cfg
    )
    free_keys: set[tuple[int, int]] = set()
    if cam_xyz.shape[0]:
        _, free_keys = _grid_cells(cam_xyz[:, [0, 2]], bin_m)
    if o.ray_carve:
        free_keys |= _carve_free_space(cam_xyz, points, bin_m, o.free_stride)
    free_cells = _keys_to_cells(free_keys, bin_m)
    stats = _evidence_stats(cam_xyz, floor_keys, wall_keys, bin_m)

    unfiltered: dict[str, object] | None = None
    if points_unfiltered is not None:
        uw, ufc, _ufk, _uwk, _ = _evidence_layers(
            points_unfiltered, cam_xyz, floor_y, ceil_y, params, cfg
        )
        unfiltered = {
            "wall_cells": _capped(uw, EVIDENCE_LAYER_CAP),
            "floor_cells": _capped(ufc, EVIDENCE_LAYER_CAP),
            "counts": {"wall_cells": len(uw), "floor_cells": len(ufc)},
            "note": "range/confidence gates OFF (raw evidence before stage-1 filters)",
        }

    capped = False

    def _cap(cells: list) -> list:
        nonlocal capped
        out = _capped(cells, EVIDENCE_LAYER_CAP)
        capped = capped or len(out) < len(cells)
        return out

    payload: dict[str, object] = {
        "name": "observed evidence",
        "params": {
            "confidence_min": o.confidence_min,
            "max_range_m": o.max_range_m,
            "evidence_bin_m": bin_m,
            "floor_band_m": o.floor_band_m,
            "height_bins": params.height_bins,
            "min_height_bins": params.min_height_bins,
            "wall_min_m": params.wall_min_m,
            "wall_max_m": params.wall_max_m,
            "wall_cell_m": params.cell_m,
            "ray_carve": o.ray_carve,
        },
        "camera_travel_m": round(camera_travel_m(cam_xyz), 3),
        "camera_xz": _camera_path_xz(cam_xyz),
        "layers": {
            "wall_cells": _cap(wall_layer),
            "floor_cells": _cap(floor_cells),
            "camera_free_space": _cap(free_cells),
        },
        "layer_counts": {
            "wall_cells": len(wall_layer),
            "floor_cells": len(floor_cells),
            "camera_free_space": len(free_cells),
        },
        "statistics": stats,
        "unfiltered": unfiltered,
        "warnings": warnings,
    }
    if capped:
        warnings.append(f"evidence layers capped at {EVIDENCE_LAYER_CAP} cells for size")
    return payload


def _component_bbox_polygon(
    cu: float, cv: float, du: float, dv: float, theta_rad: float
) -> list[list[float]]:
    """Axis-aligned (in uv) component box -> world XZ polygon."""
    corners_uv = np.array(
        [
            [cu - du / 2, cv - dv / 2],
            [cu + du / 2, cv - dv / 2],
            [cu + du / 2, cv + dv / 2],
            [cu - du / 2, cv + dv / 2],
        ]
    )
    world = rotate2d(corners_uv, -theta_rad)
    return [[float(a), float(b)] for a, b in world]


def stage2_classify(
    points: NDArray[np.float64],
    theta_rad: float,
    fit: dict[str, object],
    params: wm.WallParams,
    cfg: Config,
) -> tuple[list[Region], dict[str, int], set[str]]:
    """Label every wall-band region with one label + rule (plan 04i section 3).

    Returns (regions, counts_by_label, occluded_sides).
    """
    walls = fit["walls_uv"]  # type: ignore[index]
    floor_y = float(fit["floor_y"])  # type: ignore[index]
    band = points[(points[:, 1] > floor_y + params.wall_min_m)]
    if walls is None or None in walls.values() or band.shape[0] == 0:
        return [], {k: 0 for k in LABELS}, set()
    u0, u1 = float(walls["u_min"]), float(walls["u_max"])
    v0, v1 = float(walls["v_min"]), float(walls["v_max"])
    o = cfg.outline

    rot = rotate2d(band[:, [0, 2]], theta_rad)
    heights = band[:, 1] - floor_y
    bin_m = 0.10
    x0 = float(math.floor(rot[:, 0].min() / bin_m) * bin_m) - bin_m
    z0 = float(math.floor(rot[:, 1].min() / bin_m) * bin_m) - bin_m
    nc = int(math.ceil((rot[:, 0].max() - x0) / bin_m)) + 2
    nr = int(math.ceil((rot[:, 1].max() - z0) / bin_m)) + 2
    ix = np.clip(((rot[:, 0] - x0) / bin_m).astype(np.int64), 0, nc - 1)
    iz = np.clip(((rot[:, 1] - z0) / bin_m).astype(np.int64), 0, nr - 1)
    grid = np.zeros((nr, nc), dtype=bool)
    grid[iz, ix] = True
    hmax = np.zeros((nr, nc), dtype=np.float64)
    np.maximum.at(hmax, (iz, ix), heights)
    lab, n = ndimage.label(grid, structure=np.ones((3, 3), dtype=bool))

    regions: list[Region] = []
    counts = {k: 0 for k in LABELS}
    occluded_sides: set[str] = set()
    for c in range(1, n + 1):
        rows, cols = np.nonzero(lab == c)
        cu = x0 + (cols + 0.5) * bin_m
        cv = z0 + (rows + 0.5) * bin_m
        run = max(wm.longest_run(cu), wm.longest_run(cv))
        max_h = float(hmax[lab == c].max())
        uu, vv = float(cu.mean()), float(cv.mean())
        inset = min(abs(uu - u0), abs(uu - u1), abs(vv - v0), abs(vv - v1))
        inside = (u0 - 0.15 <= uu <= u1 + 0.15) and (v0 - 0.15 <= vv <= v1 + 0.15)
        side = min(
            (
                ("u_min", abs(uu - u0)),
                ("u_max", abs(uu - u1)),
                ("v_min", abs(vv - v0)),
                ("v_max", abs(vv - v1)),
            ),
            key=lambda s: s[1],
        )[0]

        if not inside:
            label, rule = "noise_or_ghost", "beyond_nearest_wall_line"
        elif inset <= 0.10 and run >= o.min_run_m:
            label, rule = "wall", "long_run_aligned_to_manhattan"
        elif inset <= 0.10:
            label, rule = "tall_furniture", "run_below_min_run"
        elif o.occluder_inset_m[0] <= inset <= o.occluder_inset_m[1] and run >= o.min_run_m:
            label, rule = "suspected_occluder", "long_flat_inset_from_wall_line"
            occluded_sides.add(side)
        elif max_h <= o.furniture_max_m:
            label, rule = "low_furniture", "only_below_furniture_height"
        elif run < o.min_run_m:
            label, rule = "tall_furniture", "run_below_min_run"
        else:
            label, rule = "noise_or_ghost", "unexplained_region"

        du = float(cu.max() - cu.min()) + bin_m
        dv = float(cv.max() - cv.min()) + bin_m
        poly = _component_bbox_polygon(uu, vv, du, dv, theta_rad)
        regions.append(
            Region(
                label=label,
                rule=rule,
                params={
                    "inset_m": round(inset, 3),
                    "run_m": round(run, 3),
                    "max_height_m": round(max_h, 3),
                    "min_run_m": o.min_run_m,
                    "furniture_max_m": o.furniture_max_m,
                },
                polygon_xz=poly,
                area_m2=round(du * dv, 4),
            )
        )
        counts[label] += 1
    return regions, counts, occluded_sides


def _snap_val(v: float, lines: list[float], tol: float) -> float:
    """Snap a scalar coordinate to the nearest line within ``tol``."""
    best = min(lines, key=lambda ln: abs(v - ln))
    return best if abs(v - best) <= tol else v


def _snap_ring(
    uv: NDArray[np.float64], lines_u: list[float], lines_v: list[float], tol: float
) -> NDArray[np.float64]:
    """Snap each ring coordinate to the nearest wall line within ``tol`` (plan 04i).

    Works on arbitrary (including diagonal) rings, unlike axis-detection: a vertex
    near a wall line moves onto it, a genuine notch vertex (far from every line)
    is left where it is, so concavities survive.
    """
    out = np.array(uv, dtype=np.float64, copy=True)
    for i in range(out.shape[0]):
        out[i, 0] = _snap_val(float(out[i, 0]), lines_u, tol)
        out[i, 1] = _snap_val(float(out[i, 1]), lines_v, tol)
    return out


def _orthogonalize_uv(
    uv: NDArray[np.float64], lines_u: list[float], lines_v: list[float], tol: float
) -> NDArray[np.float64]:
    """Force the ring rectilinear: each edge u- or v-constant, snapped to a wall line.

    Vertices are rebuilt as intersections of consecutive edge lines, so steps
    shorter than ``tol`` merge cleanly into their neighbour (no diagonal cuts).
    """
    n = uv.shape[0]
    edges: list[tuple[str, float]] = []
    for i in range(n):
        a, b = uv[i], uv[(i + 1) % n]
        if abs(b[0] - a[0]) >= abs(b[1] - a[1]):  # horizontal edge -> v constant
            edges.append(("v", _snap_val(float((a[1] + b[1]) / 2), lines_v, tol)))
        else:  # vertical edge -> u constant
            edges.append(("u", _snap_val(float((a[0] + b[0]) / 2), lines_u, tol)))
    merged: list[tuple[str, float]] = []
    for e in edges:
        if merged and merged[-1][0] == e[0]:
            merged[-1] = e  # consecutive same-orientation -> one run
        else:
            merged.append(e)
    if len(merged) >= 2 and merged[0][0] == merged[-1][0]:
        merged[0] = merged[-1]
        merged.pop()
    verts: list[tuple[float, float]] = []
    m = len(merged)
    for i in range(m):
        o_prev, c_prev = merged[i - 1]
        o_cur, c_cur = merged[i]
        if o_prev == "u" and o_cur == "v":
            verts.append((c_prev, c_cur))
        elif o_prev == "v" and o_cur == "u":
            verts.append((c_cur, c_prev))
    return np.asarray(verts, dtype=np.float64) if verts else uv


def _cap_edges(ring: NDArray[np.float64], max_edges: int) -> NDArray[np.float64]:
    """Drop the shortest edge (merge into neighbour) until <= ``max_edges`` vertices."""
    pts = ring.tolist()
    while len(pts) > max_edges and len(pts) > 4:
        n = len(pts)
        lengths = [
            math.hypot(pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1])
            for i in range(n)
        ]
        del pts[int(np.argmin(lengths))]
    return np.asarray(pts, dtype=np.float64)


def _ccw(ring: NDArray[np.float64]) -> NDArray[np.float64]:
    x, z = ring[:, 0], ring[:, 1]
    area2 = float(np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z))
    return ring[::-1] if area2 < 0 else ring


def _edge_support_span(
    uv: NDArray[np.float64], axis: int, pos: float, tol: float = 0.06
) -> tuple[float, float] | None:
    """Observed support span (min,max along the other axis) near a wall line."""
    if uv.shape[0] == 0:
        return None
    near = uv[np.abs(uv[:, axis] - pos) <= tol]
    if near.shape[0] == 0:
        return None
    other = near[:, 1 - axis]
    return float(other.min()), float(other.max())


def _line_extrapolation(span: tuple[float, float] | None, coord: float) -> float | None:
    """How far ``coord`` lies beyond a support span (0 if inside, None if unknown)."""
    if span is None:
        return None
    lo, hi = span
    if coord < lo:
        return lo - coord
    if coord > hi:
        return coord - hi
    return 0.0


def stage3_outline(
    floor_xz: NDArray[np.float64] | None,
    uv_cells: NDArray[np.float64] | None,
    theta_rad: float,
    walls: dict[str, float | None],
    o: Config,
) -> tuple[list[list[float]], str, bool, list[dict[str, object]]]:
    """Build the rectilinear final outline from wall items + observed floor (plan 04i).

    Stage 3 may interpolate/snap (stage 1 may not). A side with no fitted wall line
    is **inferred** from the extreme observed wall cell on that side. The room is
    rectilinear: the observed floor outline is orthogonalised and snapped to the
    fitted wall lines (so concavities/L-shapes survive), then capped to
    ``max_edges``. Each corner is ``observed`` when an observed wall cell lies
    within ``infer_tol_m``, else ``inferred`` by extending adjacent wall lines -
    with an interval that grows with the distance to the nearest evidence.
    Returns (world polygon, method, rectangular_fallback, corners).
    """
    cfg_o = o.outline
    uv = uv_cells if uv_cells is not None else np.zeros((0, 2))
    specs = (("u_min", 0, -1), ("u_max", 0, 1), ("v_min", 1, -1), ("v_max", 1, 1))
    lines: dict[str, float] = {}
    side_src: dict[str, str] = {}
    for name, axis, sign in specs:
        val = walls.get(name)
        if val is not None:
            lines[name] = float(val)
            side_src[name] = "wall"
        elif uv.shape[0]:
            coord = uv[:, axis]
            lines[name] = float(coord.min() if sign < 0 else coord.max())
            side_src[name] = "inferred"
        else:
            return [], "unavailable", True, []
    u0, u1 = lines["u_min"], lines["u_max"]
    v0, v1 = lines["v_min"], lines["v_max"]
    if u1 - u0 < 0.3 or v1 - v0 < 0.3:
        return [], "unavailable", True, []
    diagonal = float(math.hypot(u1 - u0, v1 - v0))

    # Observed concave outline (from stage-1 floor evidence), rectified + snapped.
    ring: NDArray[np.float64] | None = None
    if floor_xz is not None and floor_xz.shape[0] >= 4:
        fp = extract_footprint(floor_xz, theta_rad)
        if fp is not None and fp.ring_local.shape[0] >= 3:
            r = _snap_ring(fp.ring_local, [u0, u1], [v0, v1], cfg_o.min_step_m)
            r = merge_collinear(r, min_edge_m=cfg_o.min_step_m, chord_tol_m=cfg_o.min_step_m)
            r = _cap_edges(r, cfg_o.max_edges)
            if r.shape[0] >= 4 and abs(_poly_area(r)) >= 0.5:
                ring = _ccw(r)
    rect_fallback = ring is None
    if ring is None:
        ring = np.array([[u0, v0], [u1, v0], [u1, v1], [u0, v1]], dtype=np.float64)

    tree = cKDTree(uv) if uv.shape[0] else None
    c, s = float(np.cos(theta_rad)), float(np.sin(theta_rad))
    corners: list[dict[str, object]] = []
    for cu, cv in ring.tolist():
        dist = float(tree.query([cu, cv])[0]) if tree is not None else diagonal
        extrap = min(dist, diagonal)
        provenance = "observed" if dist <= cfg_o.infer_tol_m else "inferred"
        corners.append(
            {
                "uv": [round(cu, 4), round(cv, 4)],
                "xz": [round(cu * c - cv * s, 4), round(cu * s + cv * c, 4)],
                "provenance": provenance,
                "extrapolation_m": round(extrap, 4),
                "ci_half_m": round(cfg_o.inferred_ci_per_m * extrap, 4),
            }
        )
    world = rotate2d(ring, -theta_rad)
    if rect_fallback:
        method = (
            "wall_lines" if all(v == "wall" for v in side_src.values()) else "wall_lines_inferred"
        )
    else:
        method = "wall_lines+observed_floor"
    return [[float(a), float(b)] for a, b in world], method, rect_fallback, corners


def _poly_area(ring: NDArray[np.float64]) -> float:
    x, z = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(z, -1) - np.roll(x, -1) * z))


def detect_occluder_sides(
    uv: NDArray[np.float64],
    walls: dict[str, float | None],
    params: wm.WallParams,
    cfg: Config,
) -> dict[str, str]:
    """Sides whose fitted wall line is a **suspected occluder** (plan 04i section 3).

    A wardrobe/fridge face can be nearer than the real wall, so the fitter picks it.
    We flag the side when a *long* line also exists ``inset_min..inset_max`` metres
    further out (the real wall behind the occluder). Returns {side: rule}.
    """
    o = cfg.outline
    lo, hi = o.occluder_inset_m
    out: dict[str, str] = {}
    specs = (("u_min", 0, -1.0), ("u_max", 0, 1.0), ("v_min", 1, -1.0), ("v_max", 1, 1.0))
    for side, axis, sign in specs:
        pos = walls.get(side)
        if pos is None:
            continue
        vals = uv[:, axis]
        other = uv[:, 1 - axis]
        lo_v, hi_v = float(vals.min()) - 0.1, float(vals.max()) + 0.1
        h, edges = wm._hist1d(vals, lo_v, hi_v, cell=params.cell_m, smooth=params.peak_smooth)
        centres = (edges[:-1] + edges[1:]) / 2
        for cand in wm._peaks(h):
            offset = (centres[cand] - pos) * sign
            if not (lo <= offset <= hi):
                continue
            refined = wm._refine(vals, float(centres[cand]))
            near = other[np.abs(vals - refined) < 0.06]
            if wm.longest_run(near, max_gap=params.run_gap_m) >= params.min_run_m:
                out[side] = "long_flat_surface_inset_from_wall_line"
                break
    return out


def _nearest_side(mid_uv: tuple[float, float], walls: dict[str, float | None]) -> str:
    """Which fitted wall side an edge midpoint is closest to (or 'step')."""
    uu, vv = mid_uv
    cands = [
        ("u_min", walls.get("u_min"), abs(uu - (walls["u_min"] or 0.0))),
        ("u_max", walls.get("u_max"), abs(uu - (walls["u_max"] or 0.0))),
        ("v_min", walls.get("v_min"), abs(vv - (walls["v_min"] or 0.0))),
        ("v_max", walls.get("v_max"), abs(vv - (walls["v_max"] or 0.0))),
    ]
    side, pos, dist = min(cands, key=lambda c: c[2])
    return side if pos is not None and dist <= 0.20 else "step"


def _length_half_width(
    side: str, length: float, fit: dict[str, object], cfg: Config, state: str
) -> float:
    """Bootstrap position CI (data) + odometry term, in quadrature, widened if not clean."""
    o = cfg.outline
    pos_ci = fit.get("pos_ci") or {}
    base = 0.0
    if side in pos_ci:
        lo, hi = pos_ci[side]  # type: ignore[misc]
        if lo is not None and hi is not None:
            base = 0.5 * abs(float(hi) - float(lo))
    stat = 0.0
    if base == 0.0:  # no bootstrap sample - fall back to the fitted dim CI
        dim = "width_m" if side in ("u_min", "u_max") else "depth_m"
        ci = (fit.get(dim) or {}).get("ci") if isinstance(fit.get(dim), dict) else None
        if ci and ci[0] is not None:
            stat = 0.5 * abs(float(ci[1]) - float(ci[0]))
    odom = o.odometry_ci_frac * length
    half = math.hypot(base + stat, odom)
    if state != "observed":
        half *= o.occluded_ci_scale
    return max(half, 1e-3)


def _detect_edge_openings(
    points: NDArray[np.float64],
    a3: NDArray[np.float64],
    b3: NDArray[np.float64],
    n3: NDArray[np.float64],
    floor_y: float,
    tier: Tier,
    o: Config,
    room_id: str,
    surface_id: str,
    start_index: int,
) -> list[Opening]:
    """Door/passage gaps on one wall edge; width CI derived from the gap histogram."""
    a, b = a3[[0, 2]], b3[[0, 2]]
    d = b - a
    length = float(np.hypot(d[0], d[1]))
    if length < 1e-6:
        return []
    t_dir = d / length
    n2 = n3[[0, 2]]
    norm = float(np.hypot(n2[0], n2[1]))
    if norm < 1e-9:
        return []
    n2 = n2 / norm
    rel = points[:, [0, 2]] - a
    on_wall = np.abs(rel @ n2) <= WALL_SLAB_M
    band = (points[:, 1] >= floor_y + 0.2) & (points[:, 1] <= floor_y + DOOR_SCAN_HEIGHT_M)
    mask = on_wall & band
    if not mask.any():
        return []
    t = (points[mask][:, [0, 2]] - a) @ t_dir
    bin_w = 0.05
    bins = np.arange(0.0, length + bin_w, bin_w)
    counts, _ = np.histogram(t, bins=bins)
    occ = counts > 0
    wall_density = float(counts[occ].mean()) if occ.any() else 1.0
    openings: list[Opening] = []
    i = 0
    while i < len(occ):
        if occ[i]:
            i += 1
            continue
        j = i
        while j < len(occ) and not occ[j]:
            j += 1
        gap_w = float(bins[j] - bins[i])
        interior = i > 0 and j < len(occ)
        if interior and DOOR_MIN_WIDTH_M <= gap_w <= DOOR_MAX_WIDTH_M:
            empty_frac = 1.0 - min(1.0, float(counts[i:j].mean()) / (wall_density + 1e-9))
            conf = max(0.0, min(1.0, empty_frac))
            half = max(bin_w * (0.5 + 0.5 * (1.0 - conf)), o.outline.odometry_ci_frac * gap_w)
            oid = f"open_{room_id}_{start_index + len(openings)}"
            openings.append(
                Opening(
                    id=oid,
                    room_id=room_id,
                    surface_id=surface_id,
                    kind="door",
                    width=_measurement(
                        f"{oid}.width", "opening_width", gap_w, "m", half, "wall_gap", tier
                    ),
                    detection_confidence=round(conf, 3),
                )
            )
        i = j
    return openings


def _camera_inside_fraction(
    poly_xz: list[list[float]], cam_xyz: NDArray[np.float64]
) -> float | None:
    """Fraction of camera positions inside the final polygon (plan 04i stage 3).

    This is where the "camera must be inside the room" check lives - an assertion
    about the *final* polygon, not about stage-1 evidence.
    """
    if len(poly_xz) < 3 or cam_xyz.shape[0] == 0:
        return None
    pg = Polygon(poly_xz)
    inside = sum(1 for x, z in cam_xyz[:, [0, 2]] if pg.contains(Point(float(x), float(z))))
    return inside / cam_xyz.shape[0]


def build_outline(
    points: NDArray[np.float64],
    cam_xyz: NDArray[np.float64],
    *,
    tier: Tier,
    floor_y: float,
    ceil_y: float | None,
    cfg: Config,
    room_id: str = "room_0",
    name: str | None = None,
    points_unfiltered: NDArray[np.float64] | None = None,
) -> OutlineResult:
    """Run stages 1-3 and assemble the CIR room/surfaces/openings/measures."""
    p = wall_params_from_config(cfg)
    fit = wm.fit_room(
        points,
        cam_xyz,
        floor_y,
        ceil_y,
        params=p,
        n_boot=cfg.outline.bootstrap_n,
        seed=cfg.seed,
    )
    warnings = [str(w) for w in fit.get("warnings", [])]  # type: ignore[union-attr]
    theta = math.radians(float(fit.get("theta_deg", 0.0)))

    st1 = observed_evidence(points, cam_xyz, floor_y, ceil_y, p, cfg, points_unfiltered)
    warnings += [str(w) for w in st1["warnings"]]  # type: ignore[union-attr]
    regions, counts, occluded_sides = stage2_classify(
        points, theta, {**fit, "floor_y": floor_y}, p, cfg
    )
    walls = fit.get("walls_uv") or {}
    uv_cells = fit.get("uv")
    if isinstance(uv_cells, np.ndarray) and uv_cells.shape[0] and walls:
        occluder_map = detect_occluder_sides(uv_cells, walls, p, cfg)  # type: ignore[arg-type]
    else:
        occluder_map = {}
    occluded_sides = set(occluded_sides) | set(occluder_map)
    for side, rule in occluder_map.items():
        warnings.append(
            f"suspected_occluder on {side}: {rule} "
            "(wall kept, state=partially_occluded, interval widened)"
        )
    slab = points[np.abs(points[:, 1] - floor_y) <= cfg.outline.floor_band_m]
    floor_xz = slab[:, [0, 2]]
    poly, method, rect_fallback, corners = stage3_outline(floor_xz, uv_cells, theta, walls, cfg)  # type: ignore[arg-type]
    if not poly:
        raise ValueError("room outline unavailable (too few wall cells)")

    ring_local = rotate2d(np.asarray(poly, dtype=np.float64), theta)
    area = abs(_poly_area(ring_local))
    fit_area = fit.get("area_m2")
    a_ci = fit_area.get("ci") if isinstance(fit_area, dict) else None
    area_base = 0.5 * abs(float(a_ci[1]) - float(a_ci[0])) if a_ci and a_ci[0] is not None else 0.0
    area_half = math.hypot(area_base, cfg.outline.odometry_ci_frac * area)
    floor_area = _measurement(
        f"{room_id}.floor_area", "floor_area", area, "m2", area_half, "stage3", tier
    )
    ceiling_height = None
    if ceil_y is not None:
        ceil_h = ceil_y - floor_y
        ceiling_height = _measurement(
            f"{room_id}.ceiling_height",
            "ceiling_height",
            ceil_h,
            "m",
            cfg.outline.odometry_ci_frac * ceil_h + 0.02,
            "plane_fit",
            tier,
        )
    room = Room(
        id=room_id,
        name=name,
        boundary=poly,
        ceiling_height=ceiling_height,
        floor_area=floor_area,
    )

    n = ring_local.shape[0]
    ring_world = np.asarray(poly, dtype=np.float64)
    surfaces: list[Surface] = []
    measures: list[Measurement] = []
    segments: list[tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]] = []
    wall_ids: list[str] = []
    edge_meta: list[dict[str, object]] = []
    perimeter = 0.0
    for i in range(n):
        a_w, b_w = ring_world[i], ring_world[(i + 1) % n]
        dx, dz = float(b_w[0] - a_w[0]), float(b_w[1] - a_w[1])
        length = float(math.hypot(dx, dz))
        if length < 1e-9:
            continue
        perimeter += length
        if length < MIN_WALL_LEN_M:
            continue
        n_world = np.array([dz, -dx], dtype=np.float64) / length  # outward (CCW)
        n3 = np.array([float(n_world[0]), 0.0, float(n_world[1])])
        a3 = np.array([float(a_w[0]), floor_y, float(a_w[1])])
        b3 = np.array([float(b_w[0]), floor_y, float(b_w[1])])
        d = float(-(n3[0] * a3[0] + n3[2] * a3[2]))
        mid_uv = rotate2d(np.array([[(a_w[0] + b_w[0]) / 2, (a_w[1] + b_w[1]) / 2]]), theta)[0]
        side = _nearest_side((float(mid_uv[0]), float(mid_uv[1])), walls)  # type: ignore[arg-type]
        cov_map = fit.get("coverage") or {}
        cov = cov_map.get(side) if isinstance(cov_map, dict) and side != "step" else None
        if side == "step":
            state = "observed"
        elif cov is None:
            state = "unobserved"
        elif side in occluded_sides:
            state = "partially_occluded"
        elif float(cov) < cfg.outline.weak_coverage_frac:
            state = "partially_observed"
        else:
            state = "observed"
        half = _length_half_width(side if side != "step" else "u_min", length, fit, cfg, state)
        # Provenance (plan 04i stage 3): observed if both adjacent corners are
        # observed, else inferred; the interval grows with the extrapolated distance.
        extrap_max = 0.0
        provs: list[str] = []
        if corners and len(corners) == n:
            for ci in (i, (i + 1) % n):
                provs.append(str(corners[ci]["provenance"]))
                extrap_max = max(extrap_max, float(corners[ci]["extrapolation_m"]))
        provenance = "inferred" if (provs and any(p == "inferred" for p in provs)) else "observed"
        half = math.hypot(half, cfg.outline.inferred_ci_per_m * extrap_max)
        wall_id = f"{room_id}_wall_{len(surfaces) + 1}"
        surfaces.append(
            Surface(
                id=wall_id,
                room_id=room_id,
                type="wall",
                plane=Plane(normal=[n3[0], n3[1], n3[2]], d=d),
                polygon=[[float(a_w[0]), float(a_w[1])], [float(b_w[0]), float(b_w[1])]],
            )
        )
        measures.append(
            _measurement(f"{wall_id}.length", "wall_length", length, "m", half, "stage3", tier)
        )
        segments.append((a3, b3, n3))
        wall_ids.append(wall_id)
        edge_meta.append(
            {
                "id": wall_id,
                "side": side,
                "state": state,
                "provenance": provenance,
                "extrapolation_m": round(extrap_max, 4),
                "coverage": cov,
                "length_m": round(length, 4),
                "ci_half_m": round(half, 4),
            }
        )

    surfaces.append(
        Surface(
            id=f"{room_id}_floor",
            room_id=room_id,
            type="floor",
            plane=Plane(normal=[0.0, 1.0, 0.0], d=float(-floor_y)),
            polygon=poly,
        )
    )
    if ceil_y is not None:
        surfaces.append(
            Surface(
                id=f"{room_id}_ceiling",
                room_id=room_id,
                type="ceiling",
                plane=Plane(normal=[0.0, -1.0, 0.0], d=float(ceil_y)),
                polygon=poly,
            )
        )
    measures.append(
        _measurement(
            f"{room_id}.perimeter",
            "perimeter",
            perimeter,
            "m",
            2 * cfg.outline.odometry_ci_frac * perimeter + 0.02,
            "stage3",
            tier,
        )
    )

    openings: list[Opening] = []
    idx = 1
    for (a3, b3, n3), wall_id in zip(segments, wall_ids, strict=True):
        got = _detect_edge_openings(points, a3, b3, n3, floor_y, tier, cfg, room_id, wall_id, idx)
        openings.extend(got)
        idx += len(got)

    # Relocated "camera must be inside the room" assertion (plan 04i req. 4).
    camera_inside_frac = _camera_inside_fraction(poly, cam_xyz)
    if camera_inside_frac is not None and camera_inside_frac < 0.99:
        msg = (
            f"camera path not fully inside the final polygon "
            f"({camera_inside_frac:.0%} inside) - stage-3 assertion fired"
        )
        warnings.append(msg)
        if cfg.outline.assert_camera_inside:
            raise ValueError(msg)

    stage2 = {
        "regions": [
            {
                "label": r.label,
                "rule": r.rule,
                "params": r.params,
                "polygon_xz": r.polygon_xz,
                "area_m2": r.area_m2,
            }
            for r in regions
        ],
        "counts": counts,
        "occluded_sides": sorted(occluded_sides),
    }
    stage3 = {
        "method": method,
        "rectangular_fallback": rect_fallback,
        "polygon_xz": poly,
        "area_m2": round(area, 3),
        "n_edges": int(n),
        "walls": edge_meta,
        "corners": corners,
        "camera_inside_fraction": camera_inside_frac,
        "inferred_walls": sum(1 for w in edge_meta if w.get("provenance") == "inferred"),
        "occluded_sides": sorted(occluded_sides),
        "warnings": warnings,
    }
    return OutlineResult(
        room=room,
        surfaces=surfaces,
        openings=openings,
        measures=measures,
        stage1=st1,
        stage2=stage2,
        stage3=stage3,
        warnings=warnings,
    )
