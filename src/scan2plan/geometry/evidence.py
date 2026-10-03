"""Stage 1: observed-evidence layers (plan 04i).

Pure evidence only - **no** hull, buffer, snapping or interpolation (that is stage
3). Two filters are applied upstream in S2 (``confidence_min``, ``max_range_m``);
stage 1 then reports three layers:

  * **wall cells** - wall-band XZ cells, each with a per-cell height-bin support
    count (a vertical surface is occupied at many heights; furniture is not),
  * **floor cells** - XZ cells within the floor slab,
  * **camera free-space** - cells on the camera path (+ optional ray carve).

Unknown area stays blank. Statistics are report-only and stage 1 never fails. All
thresholds come from the I4 ``outline`` block and are recorded in the payload.

This module is self-contained on purpose: the reference wall-fitting lives in
``scan2plan.geometry.room_fit`` but is **not** used here (kept for reference only).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree

from scan2plan.config import Config

#: Cap on cells serialised per layer, so the evidence sidecar stays readable.
EVIDENCE_LAYER_CAP = 60000


def wall_cells_with_support(
    pts: NDArray[np.float64],
    floor_y: float,
    ceil_y: float | None,
    cfg: Config,
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Every wall-band XZ cell with its height-bin support count (plan 04i stage 1).

    The wall band is floor+``wall_min_m`` .. min(ceiling-0.25, floor+``wall_max_m``).
    ``min_height_bins`` is a *classification* decision (stage 2), so stage 1 keeps
    the raw per-cell counts. Returns ``(cells (M,2), counts (M,))``.
    """
    o = cfg.outline
    if pts.size == 0:
        return np.zeros((0, 2)), np.zeros((0,), dtype=np.int64)
    y_lo = floor_y + o.wall_min_m
    y_hi = (ceil_y - 0.25) if ceil_y is not None else floor_y + o.wall_max_m
    band = pts[(pts[:, 1] > y_lo) & (pts[:, 1] < y_hi)]
    if len(band) == 0:
        return np.zeros((0, 2)), np.zeros((0,), dtype=np.int64)

    ix_raw = np.floor(band[:, 0] / o.cell_m).astype(np.int64)
    iz_raw = np.floor(band[:, 2] / o.cell_m).astype(np.int64)
    hb = np.clip(
        ((band[:, 1] - y_lo) / (y_hi - y_lo) * o.height_bins).astype(np.int64),
        0,
        o.height_bins - 1,
    )
    x0, z0 = int(ix_raw.min()), int(iz_raw.min())
    ix = ix_raw - x0
    iz = iz_raw - z0
    stride = int(iz.max()) + 1
    cid = ix * stride + iz
    pair = np.unique(cid * o.height_bins + hb)
    cells, counts = np.unique(pair // o.height_bins, return_counts=True)
    cx = ((cells // stride) + x0 + 0.5) * o.cell_m
    cz = ((cells % stride) + z0 + 0.5) * o.cell_m
    return np.stack([cx, cz], axis=1), counts.astype(np.int64)


def camera_travel_m(cam_xyz: NDArray[np.float64]) -> float:
    """Total path length of the camera centres (metres) - a plausibility signal."""
    if cam_xyz.shape[0] < 2:
        return 0.0
    d = np.diff(cam_xyz[:, [0, 2]], axis=0)
    return float(np.sum(np.hypot(d[:, 0], d[:, 1])))


def _grid_cells(
    xz: NDArray[np.float64], bin_m: float
) -> tuple[list[list[float]], set[tuple[int, int]]]:
    """Deduplicate XZ points to occupied grid cells (pure binning)."""
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
    """Report-only statistics (never fail): camera inside evidence + extents."""
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


def _evidence_layers(
    points: NDArray[np.float64],
    floor_y: float,
    ceil_y: float | None,
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
    wcells, wcounts = wall_cells_with_support(points, floor_y, ceil_y, cfg)
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


def _cam_endpoint(cam_xyz: NDArray[np.float64], idx: int) -> list[float] | None:
    """First/last camera position (world XZ) so the path start/end can be marked."""
    if cam_xyz.shape[0] == 0:
        return None
    return [round(float(cam_xyz[idx, 0]), 3), round(float(cam_xyz[idx, 2]), 3)]


def observed_evidence(
    points: NDArray[np.float64],
    cam_xyz: NDArray[np.float64],
    floor_y: float,
    ceil_y: float | None,
    cfg: Config,
    points_unfiltered: NDArray[np.float64] | None = None,
) -> dict[str, object]:
    """Stage 1: pure observed evidence as layers - no hull/buffer/snap/interp (04i).

    Layers: wall cells (with per-cell support), floor cells, camera free-space
    (path, optionally ray-carved). Unknown stays blank. Reports statistics only
    (camera-inside fraction, extents) and never fails. An *unfiltered* layer
    (range/confidence gates off) is added for comparison when provided.
    """
    o = cfg.outline
    warnings: list[str] = []
    wall_layer, floor_cells, floor_keys, wall_keys, bin_m = _evidence_layers(
        points, floor_y, ceil_y, cfg
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
        uw, ufc, _ufk, _uwk, _ = _evidence_layers(points_unfiltered, floor_y, ceil_y, cfg)
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
            "cell_m": o.cell_m,
            "height_bins": o.height_bins,
            "min_height_bins": o.min_height_bins,
            "wall_min_m": o.wall_min_m,
            "wall_max_m": o.wall_max_m,
            "ray_carve": o.ray_carve,
        },
        "camera_travel_m": round(camera_travel_m(cam_xyz), 3),
        "camera_xz": _camera_path_xz(cam_xyz),
        "camera_start": _cam_endpoint(cam_xyz, 0),
        "camera_end": _cam_endpoint(cam_xyz, -1),
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
