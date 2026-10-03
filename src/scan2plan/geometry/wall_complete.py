"""Stage 2 wall completion: bridge broken wall lines WITHOUT erasing openings (04i).

Works in the Manhattan (u, v) frame that stage 2 already uses. Given the observed
wall segments, a set of dense unexplained "furniture" cells, and the ordered camera
path, every gap between two collinear segments is decided **once**:

    camera path crosses a gap of width in [open_min_m, open_max_m] -> OPENING
    camera path crosses a narrower gap (< open_min_m)   -> BRIDGE  inferred_dropout
    camera path crosses a wider gap (> open_max_m)      -> OPEN_SPACE (walk-through)
    furniture cells stand in front of it                -> BRIDGE  inferred_occluded
    short gap (<= ``dropout_max_m``)                    -> BRIDGE  inferred_dropout
    otherwise                                           -> UNKNOWN left open, flagged

Dangling ends are extended to a perpendicular wall (provenance
``inferred_extension``) unless the camera path crosses the extension. Every inferred
piece carries an interval half-width that grows with the assumed length:
``ci = ci_base_m + ci_per_m * assumed_length``.

After completion the pieces are **merged** (:func:`merge_wall_pieces`): parallel
same-axis pieces whose offsets are within ``merge_tol_m`` and whose spans overlap or
abut become one wall, recording its ``thickness`` (double-face walls collapse).

This module is a pure, deterministic function of its inputs (no RNG); **all**
thresholds come from the I4 ``outline`` block (built with
:func:`completion_params_from_config`), never from code.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from numpy.typing import NDArray

from scan2plan.config import Config

#: Provenance values a completed wall piece may carry.
OBSERVED = "observed"
OCCLUDED = "inferred_occluded"
DROPOUT = "inferred_dropout"
EXTENSION = "inferred_extension"
#: Piece kinds in the result lists.
KIND_WALL = "wall"
KIND_OPENING = "opening"
KIND_OPEN_SPACE = "open_space"
KIND_UNKNOWN = "unknown"

#: A gap smaller than this (metres) is treated as already-closed (no piece at all).
MIN_GAP_M = 0.02


@dataclass(frozen=True)
class CompletionParams:
    """Wall-completion thresholds (mirrors the I4 ``outline`` block)."""

    collinear_tol_m: float = 0.15  # segments within this offset difference are one line
    occ_band_m: float = 0.80  # furniture within this distance of the line counts
    occ_min_cells: int = 40  # cells needed to call it "furniture in front"
    dropout_max_m: float = 0.30  # short gaps bridged as sensor dropout
    max_extend_m: float = 1.00  # max junction extension
    perp_tol_m: float = 0.10  # tolerance when testing whether a line meets a wall
    ci_base_m: float = 0.03  # interval floor for an inferred piece
    ci_per_m: float = 0.15  # extra interval per metre of assumption
    open_min_m: float = 0.50  # narrower camera-crossed gaps are dropouts, not doors
    open_max_m: float = 2.50  # wider camera-crossed gaps are open_space, not doors
    merge_tol_m: float = 0.25  # parallel pieces within this offset merge into one wall


def completion_params_from_config(cfg: Config) -> CompletionParams:
    """Build ``CompletionParams`` from the I4 ``outline`` block (single source of truth)."""
    o = cfg.outline
    return CompletionParams(
        collinear_tol_m=o.collinear_tol_m,
        occ_band_m=o.occ_band_m,
        occ_min_cells=o.occ_min_cells,
        dropout_max_m=o.dropout_max_m,
        max_extend_m=o.max_extend_m,
        perp_tol_m=o.perp_tol_m,
        ci_base_m=o.ci_base_m,
        ci_per_m=o.ci_per_m,
        open_min_m=o.open_min_m,
        open_max_m=o.open_max_m,
        merge_tol_m=o.merge_tol_m,
    )


@dataclass
class WallPiece:
    """A wall segment / opening / unknown gap in the Manhattan uv frame.

    ``axis`` 0 = a line ``u = offset`` running along ``v``; axis 1 = a line
    ``v = offset`` running along ``u`` (the stage-2 / ``room_fit`` convention).
    """

    axis: int
    offset: float
    start: float
    end: float
    provenance: str = OBSERVED
    rule: str = ""
    ci_m: float = 0.0
    extension: float = 0.0
    kind: str = KIND_WALL
    support: int = 0
    coverage: float = 0.0
    thickness: float = 0.0
    merged_from: int = 1
    peak_strength: float = 0.0

    @property
    def length(self) -> float:
        """Span length (m)."""
        return float(self.end - self.start)


@dataclass
class CompletionResult:
    """What wall completion produces: walls (observed + inferred), openings, unknowns."""

    walls: list[WallPiece] = field(default_factory=list)
    openings: list[WallPiece] = field(default_factory=list)
    unknown_gaps: list[WallPiece] = field(default_factory=list)
    open_spaces: list[WallPiece] = field(default_factory=list)


# ---------------------------------------------------------------------------
# evidence probes
# ---------------------------------------------------------------------------
def _path_crosses(
    cam_uv: NDArray[np.float64], axis: int, offset: float, g0: float, g1: float
) -> bool:
    """Does the camera path cross the gap ``[g0, g1]`` on line ``(axis, offset)``?"""
    if cam_uv.shape[0] < 2:
        return False
    p, q = cam_uv[:-1], cam_uv[1:]
    d0, d1 = p[:, axis] - offset, q[:, axis] - offset
    cross = d0 * d1 < 0
    if not cross.any():
        return False
    t = d0[cross] / (d0[cross] - d1[cross])
    other = p[cross, 1 - axis] + t * (q[cross, 1 - axis] - p[cross, 1 - axis])
    return bool(((other >= g0) & (other <= g1)).any())


def _furniture_in_front(
    occ_uv: NDArray[np.float64],
    axis: int,
    offset: float,
    g0: float,
    g1: float,
    band: float,
    min_cells: int,
) -> bool:
    """True when dense unexplained cells sit within ``band`` of the line over the gap."""
    if occ_uv.shape[0] == 0:
        return False
    near = np.abs(occ_uv[:, axis] - offset) < band
    along = (occ_uv[:, 1 - axis] >= g0 - 0.2) & (occ_uv[:, 1 - axis] <= g1 + 0.2)
    return int((near & along).sum()) >= min_cells


def _group_collinear(segments: list[WallPiece], tol: float) -> list[list[WallPiece]]:
    """Group observed segments that lie on the same line (offset within ``tol``)."""
    groups: list[list[WallPiece]] = []
    for s in sorted(segments, key=lambda s: (s.axis, s.offset, s.start)):
        for g in groups:
            if g[0].axis == s.axis and abs(g[0].offset - s.offset) <= tol:
                g.append(s)
                break
        else:
            groups.append([s])
    return groups


# ---------------------------------------------------------------------------
# core: complete the walls
# ---------------------------------------------------------------------------
def complete_walls(
    segments: list[WallPiece],
    occ_uv: NDArray[np.float64],
    cam_uv: NDArray[np.float64],
    params: CompletionParams,
) -> CompletionResult:
    """Bridge broken collinear walls (without erasing openings) + extend dangling ends.

    Returns observed + inferred wall pieces, the openings the camera walked through,
    and the unresolved (evidence-free) gaps that are left open and flagged.
    """
    result = CompletionResult(walls=[replace(s) for s in segments])
    # ---- 1. gaps along collinear lines ---------------------------------
    for group in _group_collinear(segments, params.collinear_tol_m):
        axis = group[0].axis
        off = float(np.mean([s.offset for s in group]))
        ordered = sorted(group, key=lambda s: s.start)
        reach = ordered[0].end
        for s in ordered[1:]:
            g0, g1 = reach, s.start
            if g1 - g0 > MIN_GAP_M:  # a real gap
                length = g1 - g0
                if _path_crosses(cam_uv, axis, off, g0, g1):
                    if length < params.open_min_m:
                        # camera walked over a gap too narrow to be a door: dropout
                        result.walls.append(
                            WallPiece(
                                axis=axis,
                                offset=off,
                                start=g0,
                                end=g1,
                                provenance=DROPOUT,
                                rule="crossed_gap_below_open_min",
                                ci_m=params.ci_base_m + params.ci_per_m * length,
                            )
                        )
                    elif length > params.open_max_m:
                        # camera crossed a wide gap -> open space (walk-through), not a door
                        result.open_spaces.append(
                            WallPiece(
                                axis=axis,
                                offset=off,
                                start=g0,
                                end=g1,
                                kind=KIND_OPEN_SPACE,
                                rule="camera_crossed_wide_gap",
                            )
                        )
                    else:
                        result.openings.append(
                            WallPiece(
                                axis=axis,
                                offset=off,
                                start=g0,
                                end=g1,
                                kind=KIND_OPENING,
                                rule="camera_path_crosses_gap",
                            )
                        )
                elif _furniture_in_front(
                    occ_uv, axis, off, g0, g1, params.occ_band_m, params.occ_min_cells
                ):
                    result.walls.append(
                        WallPiece(
                            axis=axis,
                            offset=off,
                            start=g0,
                            end=g1,
                            provenance=OCCLUDED,
                            rule="furniture_in_front_of_gap",
                            ci_m=params.ci_base_m + params.ci_per_m * length,
                        )
                    )
                elif length <= params.dropout_max_m:
                    result.walls.append(
                        WallPiece(
                            axis=axis,
                            offset=off,
                            start=g0,
                            end=g1,
                            provenance=DROPOUT,
                            rule="short_gap",
                            ci_m=params.ci_base_m + params.ci_per_m * length,
                        )
                    )
                else:
                    result.unknown_gaps.append(
                        WallPiece(
                            axis=axis,
                            offset=off,
                            start=g0,
                            end=g1,
                            kind=KIND_UNKNOWN,
                            rule="long_gap_no_evidence",
                        )
                    )
            reach = max(reach, s.end)

    # ---- 2. extend dangling ends to a perpendicular wall ---------------
    for s in segments:
        for which, sign in (("start", -1), ("end", +1)):
            e = s.start if which == "start" else s.end
            best: tuple[float, float] | None = None
            for t in segments:
                if t.axis == s.axis:
                    continue
                # does the line of s hit t's span?
                if not (t.start - params.perp_tol_m <= s.offset <= t.end + params.perp_tol_m):
                    continue
                d = (t.offset - e) * sign  # distance beyond the end
                if 0.03 < d <= params.max_extend_m and (best is None or d < best[0]):
                    best = (d, t.offset)
            if best is None:
                continue
            d, target = best
            g0, g1 = sorted((e, target))
            if _path_crosses(cam_uv, s.axis, s.offset, g0, g1):
                continue  # camera went through: not a wall
            result.walls.append(
                WallPiece(
                    axis=s.axis,
                    offset=s.offset,
                    start=g0,
                    end=g1,
                    provenance=EXTENSION,
                    rule="dangling_end_meets_wall",
                    ci_m=params.ci_base_m + params.ci_per_m * d,
                    extension=d,
                )
            )

    result.walls.sort(key=lambda w: (w.axis, w.offset, w.start))
    result.openings.sort(key=lambda o: (o.axis, o.offset, o.start))
    result.unknown_gaps.sort(key=lambda u: (u.axis, u.offset, u.start))
    result.open_spaces.sort(key=lambda u: (u.axis, u.offset, u.start))
    return result


# ---------------------------------------------------------------------------
# merge parallel same-axis pieces into one wall (cleanup before the graph)
# ---------------------------------------------------------------------------
def _spans_join(a0: float, a1: float, b0: float, b1: float) -> bool:
    """True when two along-wall spans overlap or abut (gap <= ``MIN_GAP_M``)."""
    return min(a1, b1) - max(a0, b0) >= -MIN_GAP_M


def _dominant_provenance(cluster: list[WallPiece]) -> str:
    """Provenance whose total length dominates the cluster (ties -> observed)."""
    totals: dict[str, float] = {}
    for w in cluster:
        totals[w.provenance] = totals.get(w.provenance, 0.0) + w.length
    order = [OBSERVED, EXTENSION, OCCLUDED, DROPOUT]
    return max(order, key=lambda p: (totals.get(p, 0.0), -order.index(p)))


def _merge_wall_cluster(cluster: list[WallPiece], merge_tol_m: float) -> WallPiece:
    """Collapse a cluster of parallel same-axis pieces into one wall (with thickness)."""
    if len(cluster) == 1:
        return cluster[0]
    support = sum(w.support for w in cluster)
    coverage = (
        sum(w.coverage * max(w.support, 1) for w in cluster)
        / sum(max(w.support, 1) for w in cluster)
        if cluster
        else 0.0
    )
    weights = [max(w.support, 1) for w in cluster]
    offset = sum(w.offset * wt for w, wt in zip(cluster, weights, strict=True)) / sum(weights)
    prov = _dominant_provenance(cluster)
    rule = next((w.rule for w in cluster if w.provenance == prov and w.rule), cluster[0].rule)
    return WallPiece(
        axis=cluster[0].axis,
        offset=offset,
        start=min(w.start for w in cluster),
        end=max(w.end for w in cluster),
        provenance=prov,
        rule=rule,
        kind=KIND_WALL,
        ci_m=max(w.ci_m for w in cluster),
        extension=max(w.extension for w in cluster),
        support=support,
        coverage=coverage,
        thickness=max(w.offset for w in cluster) - min(w.offset for w in cluster),
        merged_from=sum(w.merged_from for w in cluster),
        peak_strength=max(w.peak_strength for w in cluster),
    )


def merge_wall_pieces(pieces: list[WallPiece], params: CompletionParams) -> list[WallPiece]:
    """Merge parallel same-axis pieces (offset within ``merge_tol_m``, spans overlap/abut).

    Double-face walls and collinear pieces that abut collapse into one wall, recording
    its ``thickness`` (max-min offset). Openings/unknown gaps are separate lists and are
    never merged, so a real gap is not erased. Deterministic (support-weighted offsets).
    """
    out: list[WallPiece] = []
    for axis in (0, 1):
        group = sorted(
            (w for w in pieces if w.axis == axis), key=lambda w: (w.offset, w.start, w.end)
        )
        clusters: list[list[WallPiece]] = []
        for w in group:
            for cl in clusters:
                c0 = min(p.start for p in cl)
                c1 = max(p.end for p in cl)
                weights = [max(p.support, 1) for p in cl]
                co = sum(p.offset * wt for p, wt in zip(cl, weights, strict=True)) / sum(weights)
                overlap = min(c1, w.end) - max(c0, w.start)
                same_prov = all(p.provenance == w.provenance for p in cl)
                # Merge when the spans overlap, or abut *with matching provenance* (a
                # completion bridge that merely abuts keeps its own provenance).
                if (overlap > 0.0 or (same_prov and _spans_join(c0, c1, w.start, w.end))) and (
                    abs(w.offset - co) <= params.merge_tol_m
                ):
                    cl.append(w)
                    break
            else:
                clusters.append([w])
        out.extend(_merge_wall_cluster(cl, params.merge_tol_m) for cl in clusters)
    out.sort(key=lambda w: (w.axis, w.offset, w.start))
    return out
