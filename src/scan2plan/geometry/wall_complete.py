"""Stage 2 wall completion: bridge broken wall lines WITHOUT erasing openings (04i).

Works in the Manhattan (u, v) frame that stage 2 already uses. Given the observed
wall segments, a set of dense unexplained "furniture" cells, and the ordered camera
path, every gap between two collinear segments is decided **once**:

    camera path crosses the gap          -> OPENING   (never bridged)
    furniture cells stand in front of it -> BRIDGE    provenance inferred_occluded
    short gap (<= ``dropout_max_m``)     -> BRIDGE    provenance inferred_dropout
    otherwise                            -> UNKNOWN   left open, flagged

Dangling ends are extended to a perpendicular wall (provenance
``inferred_extension``) unless the camera path crosses the extension. Every inferred
piece carries an interval half-width that grows with the assumed length:
``ci = ci_base_m + ci_per_m * assumed_length``.

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
    return result
