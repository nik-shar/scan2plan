"""Stage 2: deterministic multi-segment wall extraction from stage-1 evidence (04i).

Stage 1 (frozen) emits pure observed layers - wall cells with a per-cell
height-bin ``support`` count, floor cells, the camera path (+ start/end). Stage 2
turns those noisy cells into **wall segments**, deterministically and without
re-opening the frozen stage-1 contract.

Agreed boundary
---------------
* **Input** = the frozen ``stage1_observed.json`` + ``Config`` (never the raw cloud).
* **Output** = the ``stage2_walls.{json,svg}`` sidecar: wall **segments** only.
  There is **no** closing rectangle and no rooms/openings/polygon (those are stage 3).
* **Deterministic** - no RNG; the same artifact + config => byte-identical JSON.
* **Never fails** - degenerate input yields no segments + a warning.

Pipeline
--------
1. **Support gate** - keep wall cells occupied in >= ``min_height_bins`` height bins.
2. **Manhattan frame** - dominant orthogonal angle (``22.5 deg`` on ``c00a170fe1``).
3. **All peaks, then runs** - for each axis take **every** histogram peak; on each
   peak's line, contiguous runs (gap <= ``run_gap_m``) of length >= ``min_run_m``
   become wall segments ``{axis, offset, start, end, support, coverage}``.
4. **Merge** parallel segments within ``merge_tol_m`` into one wall with a thickness.
5. **Join** L/T junctions by extending/trimming; an outward snap beyond the observed
   run is ``inferred`` and widens the length interval by the extension length.
6. **Explain** - ``evidence_explained`` = share of wall cells within
   ``evidence_tol_m`` of a segment; unexplained cells are reported (drawn red).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from scan2plan.cir import Measurement
from scan2plan.cir.measure import Tier
from scan2plan.config import Config

#: Structural constants (not decision thresholds - those live in I4 ``outline``).
RUN_STEP_M = 0.05  # along-wall run-histogram bin (m)
REFINE_HALF_M = 0.05  # median-refinement radius around a histogram peak (m)
ANGLE_STEP_DEG = 0.5  # Manhattan-angle search step (deg)
MIN_WALL_CELLS = 200  # below this the fit is meaningless (room_fit parity)
LINE_SLAB_M = 0.06  # band half-width attaching cells to a peak line (>= evidence_tol)
LOW_EXPLAINED_FRAC = 0.5  # below this the fit is warned as weak

#: The two wall axes (u = first uv coordinate, v = second).
AXES = ("u", "v")


@dataclass(frozen=True)
class WallParams:
    """The wall-extraction thresholds, injected from the I4 ``outline`` block."""

    cell_m: float
    height_bins: int
    min_height_bins: int
    peak_smooth: int
    min_peak_frac: float
    min_run_m: float
    run_gap_m: float
    merge_tol_m: float
    join_tol_m: float
    evidence_tol_m: float


def wall_params_from_config(cfg: Config) -> WallParams:
    """Build ``WallParams`` from the I4 ``outline`` block (single source of truth)."""
    o = cfg.outline
    return WallParams(
        cell_m=o.cell_m,
        height_bins=o.height_bins,
        min_height_bins=o.min_height_bins,
        peak_smooth=o.peak_smooth,
        min_peak_frac=o.min_peak_frac,
        min_run_m=o.min_run_m,
        run_gap_m=o.run_gap_m,
        merge_tol_m=o.merge_tol_m,
        join_tol_m=o.join_tol_m,
        evidence_tol_m=o.evidence_tol_m,
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
# 1-D histogram primitives
# ---------------------------------------------------------------------------
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


def _runs(
    coord: NDArray[np.float64], *, step: float = RUN_STEP_M, max_gap: float = 0.10
) -> list[tuple[float, float]]:
    """Contiguous occupied runs (metres) along a line, merging gaps <= ``max_gap``."""
    if len(coord) == 0:
        return []
    lo, hi = float(coord.min()), float(coord.max())
    bins = np.arange(lo, hi + step, step)
    if len(bins) < 2:
        return [(lo, hi)]
    h, _ = np.histogram(coord, bins=bins)
    occ = np.flatnonzero(h > 0)
    if len(occ) == 0:
        return []
    gap_bins = int(round(max_gap / step))
    runs: list[tuple[float, float]] = []
    start = prev = int(occ[0])
    for i in occ[1:]:
        idx = int(i)
        if idx - prev > gap_bins + 1:
            runs.append((float(bins[start]), float(bins[prev + 1])))
            start = idx
        prev = idx
    runs.append((float(bins[start]), float(bins[prev + 1])))
    return runs


def _coverage_bins(
    vals: NDArray[np.float64], s: float, e: float, step: float = RUN_STEP_M
) -> float:
    """Fraction of the span [s, e] with at least one cell."""
    if e <= s:
        return 0.0
    bins = np.arange(s, e + step, step)
    if len(bins) < 2:
        return 1.0 if len(vals) else 0.0
    h, _ = np.histogram(vals, bins=bins)
    return float((h > 0).mean())


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
# multi-segment extraction
# ---------------------------------------------------------------------------
@dataclass
class Segment:
    """A wall segment in the Manhattan uv frame (before world projection)."""

    axis: int  # 0 = u-line (offset is u, spans v); 1 = v-line (offset is v, spans u)
    offset: float
    start: float
    end: float
    support: int
    coverage: float
    peak_strength: float
    thickness: float = 0.0
    merged_from: int = 1
    extension: float = 0.0
    provenance: str = "observed"

    @property
    def length(self) -> float:
        """Observed span length (m) after merging/joining."""
        return float(self.end - self.start)


def extract_segments(uv: NDArray[np.float64], p: WallParams) -> list[Segment]:
    """Every histogram peak's contiguous long runs -> wall segments (all peaks)."""
    segs: list[Segment] = []
    for axis in (0, 1):
        vals = uv[:, axis]
        other = uv[:, 1 - axis]
        lo, hi = float(vals.min()) - 0.1, float(vals.max()) + 0.1
        h, edges = _hist1d(vals, lo, hi, cell=p.cell_m, smooth=p.peak_smooth)
        centres = (edges[:-1] + edges[1:]) / 2
        pk = _peaks(h)
        if len(pk) == 0:
            continue
        strongest = float(h[pk].max())
        for i in pk:
            off = _refine(vals, float(centres[i]))
            on = np.abs(vals - off) < LINE_SLAB_M
            if not on.any():
                continue
            oth = other[on]
            strength = float(h[i] / strongest) if strongest > 0 else 0.0
            for s, e in _runs(oth, step=RUN_STEP_M, max_gap=p.run_gap_m):
                if e - s < p.min_run_m:
                    continue
                inrun = (oth >= s) & (oth <= e)
                segs.append(
                    Segment(
                        axis=axis,
                        offset=float(off),
                        start=float(s),
                        end=float(e),
                        support=int(inrun.sum()),
                        coverage=_coverage_bins(oth[inrun], s, e),
                        peak_strength=strength,
                    )
                )
    return segs


def _ranges_near(a0: float, a1: float, b0: float, b1: float, gap: float) -> bool:
    """True when two along-wall ranges overlap or are within ``gap`` metres."""
    return not (a1 < b0 - gap or b1 < a0 - gap)


def _weighted_offset(cluster: list[Segment]) -> float:
    """Support-weighted mean offset of a cluster (deterministic)."""
    tot = sum(max(s.support, 1) for s in cluster)
    return sum(s.offset * max(s.support, 1) for s in cluster) / tot


def _merge_cluster(cluster: list[Segment]) -> Segment:
    """Collapse a cluster of parallel segments into one wall (with thickness)."""
    if len(cluster) == 1:
        return cluster[0]
    support = sum(s.support for s in cluster)
    cov = sum(s.coverage * s.support for s in cluster) / support if support else 0.0
    return Segment(
        axis=cluster[0].axis,
        offset=_weighted_offset(cluster),
        start=min(s.start for s in cluster),
        end=max(s.end for s in cluster),
        support=support,
        coverage=cov,
        peak_strength=max(s.peak_strength for s in cluster),
        thickness=max(s.offset for s in cluster) - min(s.offset for s in cluster),
        merged_from=len(cluster),
    )


def merge_segments(segs: list[Segment], p: WallParams) -> list[Segment]:
    """Merge parallel segments within ``merge_tol_m`` that are also along-wall adjacent."""
    out: list[Segment] = []
    for axis in (0, 1):
        group = sorted(
            (s for s in segs if s.axis == axis), key=lambda s: (s.offset, s.start, s.end)
        )
        clusters: list[list[Segment]] = []
        for seg in group:
            for cl in clusters:
                cstart = min(s.start for s in cl)
                cend = max(s.end for s in cl)
                if _ranges_near(cstart, cend, seg.start, seg.end, p.run_gap_m) and (
                    abs(seg.offset - _weighted_offset(cl)) <= p.merge_tol_m
                ):
                    cl.append(seg)
                    break
            else:
                clusters.append([seg])
        out.extend(_merge_cluster(cl) for cl in clusters)
    out.sort(key=lambda s: (s.axis, s.offset, s.start))
    return out


def join_segments(
    segs: list[Segment], p: WallParams
) -> tuple[list[Segment], list[dict[str, object]]]:
    """Snap endpoints to perpendicular wall lines (L/T junctions).

    Each endpoint snaps to the nearest perpendicular segment line within
    ``join_tol_m`` that also covers this segment's offset. An **outward** snap is an
    extension: the segment becomes ``inferred`` and its length interval widens by the
    extension length. An **inward** snap is a trim. Returns the segments + junction
    records (segment index preserved from the input order).
    """
    perp = {
        0: [s for s in segs if s.axis == 1],  # v-lines (offset v, span u)
        1: [s for s in segs if s.axis == 0],  # u-lines (offset u, span v)
    }
    junctions: list[dict[str, object]] = []
    for idx, seg in enumerate(segs):
        orig_start, orig_end = seg.start, seg.end
        for which in (0, 1):
            coord = seg.start if which == 0 else seg.end
            best: Segment | None = None
            for cand in perp[seg.axis]:
                if abs(cand.offset - coord) <= p.join_tol_m and (
                    cand.start - p.join_tol_m <= seg.offset <= cand.end + p.join_tol_m
                ):
                    if best is None or abs(cand.offset - coord) < abs(best.offset - coord):
                        best = cand
            if best is None:
                continue
            delta = best.offset - coord
            if abs(delta) < 1e-9:
                continue
            outward = best.offset < orig_start if which == 0 else best.offset > orig_end
            if which == 0:
                seg.start = best.offset
            else:
                seg.end = best.offset
            junctions.append(
                {
                    "segment_index": idx,
                    "axis": AXES[seg.axis],
                    "endpoint": "start" if which == 0 else "end",
                    "to_axis": AXES[best.axis],
                    "snap_m": round(abs(delta), 4),
                    "kind": "extend" if outward else "trim",
                }
            )
        if seg.start > seg.end:
            seg.start, seg.end = seg.end, seg.start
        ext = 0.0
        if seg.start < orig_start:
            ext += orig_start - seg.start
        if seg.end > orig_end:
            ext += seg.end - orig_end
        seg.extension = round(ext, 4)
        if ext > 1e-9:
            seg.provenance = "inferred"
    return segs, junctions


# ---------------------------------------------------------------------------
# evidence explanation: how much of the stage-1 wall cells the segments cover
# ---------------------------------------------------------------------------
def segment_point_distance(xz: NDArray[np.float64], seg: Segment) -> NDArray[np.float64]:
    """Distance (m) from each uv point to a segment (points and segment share uv)."""
    a = xz[:, seg.axis]
    b = xz[:, 1 - seg.axis]
    perp = np.abs(a - seg.offset)
    db = np.where(b < seg.start, seg.start - b, np.where(b > seg.end, b - seg.end, 0.0))
    return np.sqrt(perp**2 + db**2)


def explained_mask(xz: NDArray[np.float64], segs: list[Segment], tol: float) -> NDArray[np.bool_]:
    """Boolean mask: cells within ``tol`` metres of at least one segment."""
    if not segs or xz.shape[0] == 0:
        return np.zeros(xz.shape[0], dtype=bool)
    d = np.full(xz.shape[0], np.inf)
    for s in segs:
        d = np.minimum(d, segment_point_distance(xz, s))
    return d <= tol


def _extent_world(cells: NDArray[np.float64]) -> dict[str, list[float]] | None:
    """Bounding extents (m) of world-XZ cells."""
    if cells.shape[0] == 0:
        return None
    return {
        "x_m": [round(float(cells[:, 0].min()), 3), round(float(cells[:, 0].max()), 3)],
        "z_m": [round(float(cells[:, 1].min()), 3), round(float(cells[:, 1].max()), 3)],
    }


def _segment_out(idx: int, s: Segment, theta: float, cfg: Config, tier: Tier) -> dict[str, object]:
    """Serialise one segment in world coordinates, with a length Measurement."""
    a_uv = (s.offset, s.start) if s.axis == 0 else (s.start, s.offset)
    b_uv = (s.offset, s.end) if s.axis == 0 else (s.end, s.offset)
    a_w = _uv_to_world(a_uv[0], a_uv[1], theta)
    b_w = _uv_to_world(b_uv[0], b_uv[1], theta)
    half = max(cfg.outline.odometry_ci_frac * s.length + s.extension, 1e-4)
    length = Measurement(
        id=f"wall_{idx + 1}.length",
        kind="wall_length",
        value=round(s.length, 4),
        unit="m",
        ci_low=round(s.length - half, 4),
        ci_high=round(s.length + half, 4),
        method="wall_segment",
        tier=tier,
    )
    return {
        "id": f"wall_{idx + 1}",
        "axis": AXES[s.axis],
        "offset_m": round(s.offset, 4),
        "thickness_m": round(s.thickness, 4),
        "start_m": round(s.start, 4),
        "end_m": round(s.end, 4),
        "length": length.model_dump(),
        "provenance": s.provenance,
        "extension_m": round(s.extension, 4),
        "support": int(s.support),
        "coverage": round(s.coverage, 4),
        "peak_strength": round(s.peak_strength, 4),
        "merged_from": int(s.merged_from),
        "endpoints_world": {
            "a": [round(a_w[0], 4), round(a_w[1], 4)],
            "b": [round(b_w[0], 4), round(b_w[1], 4)],
        },
    }


def reconstruct_walls(
    stage1: dict[str, object], cfg: Config, *, tier: Tier = "lidar"
) -> dict[str, object]:
    """Stage 2: multi-segment wall extraction from the frozen stage-1 evidence (04i).

    Pure, deterministic function of ``stage1`` + ``cfg``: the support gate cleans the
    wall cells, the Manhattan frame aligns them, and **every** histogram peak yields
    contiguous long runs that become wall segments; parallel segments merge and L/T
    junctions join. No closing rectangle, no rooms. Never raises on degenerate input.
    """
    p = wall_params_from_config(cfg)
    warnings: list[str] = []

    layers = stage1.get("layers", {})
    assert isinstance(layers, dict)
    wall_cells = layers.get("wall_cells") or []

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
    all_xz = (
        np.array([[float(c["x"]), float(c["z"])] for c in wall_cells], dtype=np.float64)
        if wall_cells
        else np.empty((0, 2), dtype=np.float64)
    )

    theta = 0.0
    segments_out: list[dict[str, object]] = []
    junctions: list[dict[str, object]] = []
    total = int(all_xz.shape[0])
    n_kept = int(kept.shape[0])
    evidence: dict[str, object] = {
        "cells_total": total,
        "cells_explained": 0,
        "cells_unexplained": total,
        "evidence_explained": 0.0,
        "cells_kept": n_kept,
        "cells_kept_explained": 0,
        "evidence_explained_kept": 0.0,
    }
    if n_kept < MIN_WALL_CELLS:
        warnings.append(f"too few wall cells ({n_kept} < {MIN_WALL_CELLS}) - wall fit skipped")
    else:
        theta = manhattan_angle(kept)
        segs = merge_segments(extract_segments(rotate_xz(kept, theta), p), p)
        segs, junctions = join_segments(segs, p)
        expl = int(explained_mask(rotate_xz(all_xz, theta), segs, p.evidence_tol_m).sum())
        kept_expl = int(explained_mask(rotate_xz(kept, theta), segs, p.evidence_tol_m).sum())
        evidence = {
            "cells_total": total,
            "cells_explained": expl,
            "cells_unexplained": total - expl,
            "evidence_explained": round(expl / total, 4) if total else 0.0,
            "cells_kept": n_kept,
            "cells_kept_explained": kept_expl,
            "evidence_explained_kept": round(kept_expl / n_kept, 4) if n_kept else 0.0,
        }
        segments_out = [_segment_out(i, s, theta, cfg, tier) for i, s in enumerate(segs)]
        if not segs:
            warnings.append("no wall segments found")
        elif n_kept and float(evidence["evidence_explained_kept"]) < LOW_EXPLAINED_FRAC:
            warnings.append(
                f"low evidence_explained_kept {float(evidence['evidence_explained_kept']):.0%} "
                f"({n_kept - kept_expl} of {n_kept} kept cells unexplained)"
            )

    return {
        "name": "wall segments",
        "params": {
            "min_height_bins": p.min_height_bins,
            "cell_m": p.cell_m,
            "peak_smooth": p.peak_smooth,
            "min_peak_frac": p.min_peak_frac,
            "min_run_m": p.min_run_m,
            "run_gap_m": p.run_gap_m,
            "merge_tol_m": p.merge_tol_m,
            "join_tol_m": p.join_tol_m,
            "evidence_tol_m": p.evidence_tol_m,
        },
        "manhattan_angle_deg": round(math.degrees(theta), 3),
        "cells": cells,
        "segments": segments_out,
        "wall_count": len(segments_out),
        "inferred_count": sum(1 for s in segments_out if s["provenance"] == "inferred"),
        "junctions": junctions,
        "evidence": evidence,
        "extent_world": _extent_world(kept),
        "camera_start": stage1.get("camera_start"),
        "camera_end": stage1.get("camera_end"),
        "warnings": warnings,
    }


def segments_from_payload(stage2: dict[str, object]) -> list[Segment]:
    """Rebuild ``Segment`` objects from a serialised stage-2 payload (for rendering)."""
    out: list[Segment] = []
    raw = stage2.get("segments", []) or []
    for d in raw:
        assert isinstance(d, dict)
        out.append(
            Segment(
                axis=0 if d.get("axis") == "u" else 1,
                offset=float(d["offset_m"]),
                start=float(d["start_m"]),
                end=float(d["end_m"]),
                support=int(d.get("support", 0)),
                coverage=float(d.get("coverage", 0.0)),
                peak_strength=float(d.get("peak_strength", 0.0)),
                thickness=float(d.get("thickness_m", 0.0)),
                provenance=str(d.get("provenance", "observed")),
            )
        )
    return out
