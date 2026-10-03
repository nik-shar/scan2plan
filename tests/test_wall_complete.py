"""Tests for stage-2 wall completion (`scan2plan.geometry.wall_complete`, plan 04i).

The prototype's four situations + a dangling end, now asserted in our system:
door gap (camera crosses) must stay open; wardrobe gap (furniture in front) must
bridge; short gap must bridge as dropout; long evidence-free gap must stay open.
"""

from __future__ import annotations

import numpy as np
import pytest

from scan2plan.config import Config
from scan2plan.geometry.wall_complete import (
    DROPOUT,
    EXTENSION,
    OBSERVED,
    OCCLUDED,
    CompletionParams,
    WallPiece,
    complete_walls,
    completion_params_from_config,
    merge_wall_pieces,
)


def _piece(axis: int, offset: float, a0: float, a1: float) -> WallPiece:
    return WallPiece(axis=axis, offset=offset, start=a0, end=a1)


def _scene() -> tuple[list[WallPiece], np.ndarray, np.ndarray]:
    """The prototype's scenario: a broken wall, a wardrobe, and a dangling end."""
    rng = np.random.default_rng(0)
    seg = [
        _piece(1, 0.0, 0.0, 2.0),
        _piece(1, 0.0, 3.2, 4.5),  # gap A (1.2 m): door, camera crosses
        _piece(1, 0.0, 6.0, 7.0),  # gap B (1.5 m): wardrobe in front
        _piece(1, 0.0, 7.2, 10.0),  # gap C (0.2 m): sensor dropout
        _piece(1, 3.0, 0.0, 4.0),
        _piece(1, 3.0, 5.5, 10.0),  # gap D (1.5 m): no evidence
        _piece(0, 0.0, 0.0, 2.4),  # left wall stops 0.6 m short of the v=3 wall
    ]
    occ = np.stack([rng.uniform(4.6, 6.1, 500), rng.uniform(0.0, 0.6, 500)], 1)
    cam = np.array([[2.6, -1.0], [2.6, 1.0], [8.0, 1.5], [9.0, 2.0]])
    return seg, occ, cam


def test_prototype_scenario_decision_rules() -> None:
    seg, occ, cam = _scene()
    r = complete_walls(seg, occ, cam, CompletionParams())

    # door gap -> opening, never bridged
    op = [o for o in r.openings if abs(o.start - 2.0) < 1e-6 and abs(o.end - 3.2) < 1e-6]
    assert op and op[0].rule == "camera_path_crosses_gap"
    assert not any(w.provenance == OCCLUDED and w.start < 3.2 for w in r.walls)

    # wardrobe gap -> occluded bridge
    assert any(w.provenance == OCCLUDED and abs(w.start - 4.5) < 1e-6 for w in r.walls)

    # short gap -> dropout bridge
    assert any(w.provenance == DROPOUT for w in r.walls)

    # long evidence-free gap -> one unknown, left open
    assert len(r.unknown_gaps) == 1
    assert r.unknown_gaps[0].rule == "long_gap_no_evidence"

    # dangling left wall extends to the v=3 wall
    ext = [w for w in r.walls if w.provenance == EXTENSION]
    assert any(w.axis == 0 and abs(w.end - 3.0) < 1e-6 for w in ext)


def test_observed_segments_are_kept_as_observed() -> None:
    seg, occ, cam = _scene()
    r = complete_walls(seg, occ, cam, CompletionParams())
    observed = [w for w in r.walls if w.provenance == OBSERVED]
    assert len(observed) == len(seg)
    # inputs are not mutated
    assert all(s.provenance == OBSERVED for s in seg)


def test_inferred_pieces_carry_a_growing_interval() -> None:
    seg, occ, cam = _scene()
    params = CompletionParams()
    r = complete_walls(seg, occ, cam, params)
    for w in r.walls:
        if w.provenance != OBSERVED:
            assert w.ci_m == params.ci_base_m + params.ci_per_m * w.length


def test_completion_is_deterministic() -> None:
    seg, occ, cam = _scene()
    a = complete_walls(seg, occ, cam, CompletionParams())
    b = complete_walls(seg, occ, cam, CompletionParams())
    assert [vars(w) for w in a.walls] == [vars(w) for w in b.walls]
    assert [vars(o) for o in a.openings] == [vars(o) for o in b.openings]


def test_completion_params_from_config() -> None:
    p = completion_params_from_config(Config())
    assert p.collinear_tol_m == 0.15
    assert p.dropout_max_m == 0.30
    assert p.ci_base_m == 0.03 and p.ci_per_m == 0.15


def test_completion_params_expose_width_cap_and_merge_tol() -> None:
    p = completion_params_from_config(Config())
    assert p.open_min_m == 0.5 and p.open_max_m == 2.5
    assert p.merge_tol_m == 0.25


def _crossed_gap(gap: float) -> tuple[list[WallPiece], np.ndarray]:
    """A collinear wall broken by a gap ``gap`` the camera walks through (u = centre)."""
    segs = [_piece(1, 0.0, 0.0, 3.0), _piece(1, 0.0, 3.0 + gap, 6.0 + gap)]
    cam = np.array([[3.0 + gap / 2, -1.0], [3.0 + gap / 2, 1.0]])
    return segs, cam


def test_camera_crossed_gap_in_range_is_an_opening() -> None:
    segs, cam = _crossed_gap(1.0)
    r = complete_walls(segs, np.empty((0, 2)), cam, CompletionParams())
    assert len(r.openings) == 1
    assert r.openings[0].rule == "camera_path_crosses_gap"
    assert not r.open_spaces


def test_camera_crossed_gap_narrower_than_open_min_is_dropout() -> None:
    segs, cam = _crossed_gap(0.3)
    r = complete_walls(segs, np.empty((0, 2)), cam, CompletionParams())
    assert not r.openings
    assert any(w.provenance == DROPOUT and w.rule == "crossed_gap_below_open_min" for w in r.walls)


def test_camera_crossed_gap_wider_than_open_max_is_open_space() -> None:
    segs, cam = _crossed_gap(4.0)
    r = complete_walls(segs, np.empty((0, 2)), cam, CompletionParams())
    assert not r.openings
    assert len(r.open_spaces) == 1
    assert r.open_spaces[0].rule == "camera_crossed_wide_gap"


def test_merge_wall_pieces_overlapping_faces_collapse_with_thickness() -> None:
    pieces = [_piece(1, 0.0, 0.0, 2.0), _piece(1, 0.20, 0.5, 2.5)]
    merged = merge_wall_pieces(pieces, CompletionParams())
    assert len(merged) == 1
    m = merged[0]
    assert (m.start, m.end) == (0.0, 2.5)
    assert m.thickness == pytest.approx(0.20)
    assert m.merged_from == 2


def test_merge_wall_pieces_abutting_same_provenance_merge() -> None:
    pieces = [_piece(1, 0.0, 0.0, 2.0), _piece(1, 0.0, 2.0, 4.0)]
    assert len(merge_wall_pieces(pieces, CompletionParams())) == 1


def test_merge_wall_pieces_keep_bridge_provenance_when_only_abutting() -> None:
    pieces = [
        _piece(1, 0.0, 0.0, 2.0),
        WallPiece(axis=1, offset=0.0, start=2.0, end=2.2, provenance=DROPOUT, rule="short_gap"),
        _piece(1, 0.0, 2.2, 4.0),
    ]
    merged = merge_wall_pieces(pieces, CompletionParams())
    assert len(merged) == 3  # a bridge that only abuts keeps its own provenance
    assert any(m.provenance == DROPOUT for m in merged)
