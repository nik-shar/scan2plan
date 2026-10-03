"""Tests for the stage-2 wall graph (`scan2plan.geometry.wall_graph`, plan 04i).

Nodes are wall intersections (with inferred extensions); collinear touching segments
merge into one edge; nodes are typed L / T / cross / dangling_end; every free end is
flagged dangling (no silent open ends).
"""

from __future__ import annotations

import numpy as np
import pytest

from scan2plan.config import Config
from scan2plan.geometry.wall_complete import WallPiece
from scan2plan.geometry.wall_graph import (
    CROSS,
    DANGLING,
    GraphNode,
    L,
    T,
    _merge_nodes,
    build_wall_graph,
    graph_params_from_config,
)

P = graph_params_from_config(Config())
#: A camera far away from the synthetic walls (crosses nothing).
FAR = np.array([[10.0, 10.0], [11.0, 11.0]])


def _p(axis: int, offset: float, a0: float, a1: float, prov: str = "observed") -> WallPiece:
    return WallPiece(axis=axis, offset=offset, start=a0, end=a1, provenance=prov)


def _types(graph) -> list[str]:
    return [n.type for n in graph.nodes]


def test_l_corner() -> None:
    walls = [_p(0, 0.0, 0.0, 3.0), _p(1, 0.0, 0.0, 3.0)]
    g = build_wall_graph(walls, FAR, P)
    assert g.counts[L] == 1
    assert g.counts[DANGLING] == 2
    assert len(g.edges) == 2
    # the corner is at (0, 0)
    corner = next(n for n in g.nodes if n.type == L)
    assert (corner.u, corner.v) == (0.0, 0.0)


def test_t_junction() -> None:
    walls = [_p(0, 0.0, 0.0, 4.0), _p(1, 2.0, 0.0, 3.0)]
    g = build_wall_graph(walls, FAR, P)
    assert g.counts[T] == 1
    assert g.counts[DANGLING] == 3
    assert len(g.edges) == 3  # the vertical is split by the T
    tee = next(n for n in g.nodes if n.type == T)
    assert (tee.u, tee.v) == (0.0, 2.0)


def test_cross_junction() -> None:
    walls = [_p(0, 0.0, 0.0, 4.0), _p(1, 2.0, -2.0, 2.0)]
    g = build_wall_graph(walls, FAR, P)
    assert g.counts[CROSS] == 1
    assert g.counts[DANGLING] == 4
    assert len(g.edges) == 4


def test_merge_nodes_unit() -> None:
    nodes = [
        GraphNode(id="", u=0.0, v=0.0),
        GraphNode(id="", u=0.05, v=0.02),
        GraphNode(id="", u=5.0, v=5.0),
    ]
    merged = _merge_nodes(nodes, 0.1)
    assert len(merged) == 2


def test_collinear_touching_segments_merge_into_one_edge() -> None:
    # two touching collinear pieces on v=0, plus a stub closing the loop
    walls = [
        _p(1, 0.0, 0.0, 1.0),
        _p(1, 0.0, 1.0, 3.0),
        _p(0, 0.0, 0.0, 3.0),
    ]
    g = build_wall_graph(walls, FAR, P)
    # v=0 is one edge (0,0)->(3,0); u=0 is one edge (0,0)->(0,3)
    longs = [e for e in g.edges if e.length == pytest.approx(3.0)]
    assert len(longs) == 2
    assert len(g.edges) == 2


def test_inferred_extension_node() -> None:
    walls = [_p(0, 0.0, 0.0, 4.0), _p(1, 4.5, -2.0, 2.0)]
    g = build_wall_graph(walls, FAR, P)
    node = next(n for n in g.nodes if n.v == pytest.approx(4.5) and n.u == pytest.approx(0.0))
    assert node.inferred is True
    # the vertical was extended to reach the node -> an edge of length 4.5
    assert any(e.length == pytest.approx(4.5) for e in g.edges)


def test_camera_crossing_prevents_extension() -> None:
    walls = [_p(0, 0.0, 0.0, 4.0), _p(1, 4.5, -2.0, 2.0)]
    cam = np.array([[-1.0, 4.2], [1.0, 4.2]])  # walks through u=0 at v=4.2
    g = build_wall_graph(walls, cam, P)
    assert not any(n.v == pytest.approx(4.5) and n.u == pytest.approx(0.0) for n in g.nodes)


def test_dangling_ends_are_flagged_with_a_location() -> None:
    walls = [_p(0, 0.0, 0.0, 3.0), _p(1, 0.0, 0.0, 3.0)]
    g = build_wall_graph(walls, FAR, P)
    dangling_nodes = {n.id for n in g.nodes if n.type == DANGLING}
    assert {d.node_id for d in g.dangling} == dangling_nodes
    assert all(isinstance(d.u, float) and isinstance(d.v, float) for d in g.dangling)
    assert len(g.dangling) == g.counts[DANGLING]


def test_edges_carry_length_and_provenance() -> None:
    walls = [_p(0, 0.0, 0.0, 3.0), _p(1, 0.0, 0.0, 3.0)]
    g = build_wall_graph(walls, FAR, P)
    for e in g.edges:
        assert e.length > 0.0
        assert e.ci_m >= 0.0
        assert e.provenance == "observed"
        assert e.node_a in {n.id for n in g.nodes}
        assert e.node_b in {n.id for n in g.nodes}


def test_deterministic() -> None:
    walls = [_p(0, 0.0, 0.0, 4.0), _p(1, 2.0, -2.0, 2.0), _p(0, 3.0, 1.0, 3.0)]
    a = build_wall_graph(walls, FAR, P)
    b = build_wall_graph(walls, FAR, P)
    assert [vars(n) for n in a.nodes] == [vars(n) for n in b.nodes]
    assert [vars(e) for e in a.edges] == [vars(e) for e in b.edges]


def test_empty_graph() -> None:
    g = build_wall_graph([], FAR, P)
    assert g.nodes == [] and g.edges == [] and g.dangling == []
    assert all(v == 0 for v in g.counts.values())
