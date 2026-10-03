"""Stage-2 wall graph: turn completed wall segments into a node/edge graph (04i).

Runs **after** wall completion (``geometry/wall_complete.py``), in the same
Manhattan (u, v) frame. Every intersection of a vertical (axis 0) and horizontal
(axis 1) wall is a candidate node:

    inside both spans (tol ``node_tol_m``)              -> node
    beyond one span by <= ``max_extend_m``, camera does
    not cross the stub                                  -> node, inferred extension
    otherwise                                           -> not a node

Nodes closer than ``node_merge_m`` are merged; collinear touching segments become a
single edge (a wall line is split into edges only at its nodes). Each node is typed
by its incident wall directions (``L`` / ``T`` / ``cross`` / ``dangling_end``), and
**every** free end is reported as a dangling flag (no silent open ends).

Pure and deterministic (no RNG); thresholds come from the I4 ``outline`` block.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from numpy.typing import NDArray

from scan2plan.config import Config
from scan2plan.geometry.wall_complete import WallPiece, _path_crosses

#: Node types.
L = "L"
T = "T"
CROSS = "cross"
DANGLING = "dangling_end"
NODE_TYPES = (L, T, CROSS, DANGLING)


@dataclass(frozen=True)
class GraphParams:
    """Wall-graph thresholds (mirrors the I4 ``outline`` block)."""

    node_tol_m: float = 0.05  # an intersection counts as a node within this
    node_merge_m: float = 0.10  # nodes closer than this are the same node
    max_extend_m: float = 1.00  # max stub length that still makes a node
    collinear_tol_m: float = 0.15  # offsets within this are the same wall line
    ci_base_m: float = 0.03  # interval floor for an inferred extension
    ci_per_m: float = 0.15  # extra interval per metre of assumption


def graph_params_from_config(cfg: Config) -> GraphParams:
    """Build ``GraphParams`` from the I4 ``outline`` block (single source of truth)."""
    o = cfg.outline
    return GraphParams(
        node_tol_m=o.node_tol_m,
        node_merge_m=o.node_merge_m,
        max_extend_m=o.max_extend_m,
        collinear_tol_m=o.collinear_tol_m,
        ci_base_m=o.ci_base_m,
        ci_per_m=o.ci_per_m,
    )


@dataclass
class GraphNode:
    """A graph node: an (u, v) junction, typed by its incident wall directions."""

    id: str
    u: float
    v: float
    type: str = L
    inferred: bool = False


@dataclass
class GraphEdge:
    """A graph edge: a wall run between two nodes on the same wall line."""

    id: str
    node_a: str
    node_b: str
    length: float
    ci_m: float
    provenance: str


@dataclass
class DanglingEnd:
    """A flagged open wall end (never left silent)."""

    node_id: str
    u: float
    v: float
    reason: str


@dataclass
class WallGraph:
    """Nodes, edges, dangling flags and per-type counts."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    dangling: list[DanglingEnd] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class _WallLine:
    """A union of collinear wall pieces (the candidate edges are its sub-spans)."""

    axis: int
    offset: float
    start: float
    end: float
    provenance: str
    pieces: list[WallPiece] = field(default_factory=list)


# ---------------------------------------------------------------------------
# nodes
# ---------------------------------------------------------------------------
def _candidate_nodes(
    walls: list[WallPiece], cam_uv: NDArray[np.float64], p: GraphParams
) -> list[GraphNode]:
    """Every vertical (axis 0) x horizontal (axis 1) intersection that makes a node."""
    verticals = [w for w in walls if w.axis == 0]  # u = offset, span along v
    horizontals = [w for w in walls if w.axis == 1]  # v = offset, span along u
    raw: list[tuple[float, float, bool]] = []
    for vs in verticals:
        for hs in horizontals:
            u, v = vs.offset, hs.offset
            d_vs = max(0.0, vs.start - v, v - vs.end)  # overshoot on the vertical span
            d_hs = max(0.0, hs.start - u, u - hs.end)  # overshoot on the horizontal span
            within_vs = d_vs <= p.node_tol_m
            within_hs = d_hs <= p.node_tol_m
            if within_vs and within_hs:
                raw.append((u, v, False))
            elif within_vs and d_hs <= p.max_extend_m:
                near = hs.start if u < hs.start else hs.end
                g0, g1 = sorted((near, u))
                if not _path_crosses(cam_uv, 1, hs.offset, g0, g1):
                    raw.append((u, v, True))
                    _extend(hs, u, d_hs, p)
            elif within_hs and d_vs <= p.max_extend_m:
                near = vs.start if v < vs.start else vs.end
                g0, g1 = sorted((near, v))
                if not _path_crosses(cam_uv, 0, vs.offset, g0, g1):
                    raw.append((u, v, True))
                    _extend(vs, v, d_vs, p)
    return [GraphNode(id="", u=u, v=v, inferred=inf) for u, v, inf in raw]


def _extend(piece: WallPiece, coord: float, d: float, p: GraphParams) -> None:
    """Extend a wall piece's span to reach a node; tag it an inferred extension."""
    piece.start = min(piece.start, coord)
    piece.end = max(piece.end, coord)
    if piece.provenance == "observed":
        piece.provenance = "inferred_extension"
    piece.ci_m = max(piece.ci_m, p.ci_base_m + p.ci_per_m * d)


def _merge_nodes(nodes: list[GraphNode], merge_m: float) -> list[GraphNode]:
    """Merge nodes closer than ``merge_m`` (greedy, deterministic)."""
    clusters: list[list[GraphNode]] = []
    for n in sorted(nodes, key=lambda n: (n.u, n.v)):
        for cl in clusters:
            cu = sum(m.u for m in cl) / len(cl)
            cv = sum(m.v for m in cl) / len(cl)
            if ((n.u - cu) ** 2 + (n.v - cv) ** 2) ** 0.5 <= merge_m:
                cl.append(n)
                break
        else:
            clusters.append([n])
    merged: list[GraphNode] = []
    for cl in clusters:
        cu = sum(m.u for m in cl) / len(cl)
        cv = sum(m.v for m in cl) / len(cl)
        merged.append(GraphNode(id="", u=cu, v=cv, inferred=all(m.inferred for m in cl)))
    merged.sort(key=lambda n: (n.u, n.v))
    return merged


# ---------------------------------------------------------------------------
# wall lines (collinear segments merged into one edge-bearing line)
# ---------------------------------------------------------------------------
def _wall_lines(walls: list[WallPiece], tol: float) -> list[_WallLine]:
    """Merge collinear pieces into one wall line (touching segments -> one edge)."""
    lines: list[_WallLine] = []
    for axis in (0, 1):
        group = sorted((w for w in walls if w.axis == axis), key=lambda w: (w.offset, w.start))
        for w in group:
            for ln in lines:
                if ln.axis == axis and abs(w.offset - ln.offset) <= tol:
                    ln.pieces.append(w)
                    ln.start = min(ln.start, w.start)
                    ln.end = max(ln.end, w.end)
                    if w.provenance == "observed":
                        ln.provenance = "observed"
                    break
            else:
                lines.append(
                    _WallLine(
                        axis=axis,
                        offset=w.offset,
                        start=w.start,
                        end=w.end,
                        provenance=w.provenance,
                        pieces=[w],
                    )
                )
    for ln in lines:
        ln.offset = sum(pc.offset for pc in ln.pieces) / len(ln.pieces)
    lines.sort(key=lambda ln: (ln.axis, ln.offset, ln.start))
    return lines


# ---------------------------------------------------------------------------
# the graph
# ---------------------------------------------------------------------------
def _edge_ci(ln: _WallLine, c0: float, c1: float) -> float:
    """Max interval half-width of the pieces overlapping the edge span [c0, c1]."""
    lo, hi = min(c0, c1), max(c0, c1)
    ci = 0.0
    for pc in ln.pieces:
        if pc.start <= hi and pc.end >= lo:
            ci = max(ci, pc.ci_m)
    return ci


def build_wall_graph(
    walls: list[WallPiece], cam_uv: NDArray[np.float64], params: GraphParams
) -> WallGraph:
    """Turn completed wall pieces into a node/edge graph (plan 04i).

    Nodes are wall intersections (inferred extensions allowed); collinear touching
    segments merge into one edge; every node is typed by its incident directions; all
    free ends are flagged dangling (no silent open ends). Deterministic.
    """
    walls = [replace(w) for w in walls]  # copy: candidate nodes may extend spans
    nodes = _merge_nodes(_candidate_nodes(walls, cam_uv, params), params.node_merge_m)
    lines = _wall_lines(walls, params.collinear_tol_m)

    refs: list[tuple[int, int, float, float, str]] = []
    for ln in lines:
        on: list[int] = []
        for i, n in enumerate(nodes):
            perp = n.u if ln.axis == 0 else n.v
            coord = n.v if ln.axis == 0 else n.u
            if (
                abs(perp - ln.offset) <= params.node_tol_m
                and ln.start - params.node_merge_m <= coord <= ln.end + params.node_merge_m
            ):
                on.append(i)
        for endcoord in (ln.start, ln.end):
            near = any(
                abs((nodes[i].v if ln.axis == 0 else nodes[i].u) - endcoord) <= params.node_merge_m
                for i in on
            )
            if not near:
                nodes.append(
                    GraphNode(id="", u=ln.offset, v=endcoord)
                    if ln.axis == 0
                    else GraphNode(id="", u=endcoord, v=ln.offset)
                )
                on.append(len(nodes) - 1)
        on.sort(key=lambda i: nodes[i].v if ln.axis == 0 else nodes[i].u)
        for a, b in zip(on, on[1:], strict=False):
            ca = nodes[a].v if ln.axis == 0 else nodes[a].u
            cb = nodes[b].v if ln.axis == 0 else nodes[b].u
            length = abs(cb - ca)
            if length <= 1e-9:
                continue
            refs.append((a, b, length, _edge_ci(ln, ca, cb), ln.provenance))

    degree: dict[int, int] = {}
    for a, b, _ln, _ci, _pv in refs:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    for i, n in enumerate(nodes):
        deg = degree.get(i, 0)
        n.type = DANGLING if deg <= 1 else L if deg == 2 else T if deg == 3 else CROSS

    order = sorted(range(len(nodes)), key=lambda i: (nodes[i].u, nodes[i].v))
    idmap = {i: f"n{k + 1}" for k, i in enumerate(order)}
    final_nodes = [
        GraphNode(
            id=idmap[i],
            u=round(nodes[i].u, 4),
            v=round(nodes[i].v, 4),
            type=nodes[i].type,
            inferred=nodes[i].inferred,
        )
        for i in order
    ]
    edges = [
        GraphEdge(
            id=f"e{j + 1}",
            node_a=idmap[a],
            node_b=idmap[b],
            length=round(length, 4),
            ci_m=round(ci, 4),
            provenance=prov,
        )
        for j, (a, b, length, ci, prov) in enumerate(refs)
    ]
    dangling = [
        DanglingEnd(node_id=n.id, u=n.u, v=n.v, reason="open_end")
        for n in final_nodes
        if n.type == DANGLING
    ]
    counts = {t: sum(1 for n in final_nodes if n.type == t) for t in NODE_TYPES}
    return WallGraph(nodes=final_nodes, edges=edges, dangling=dangling, counts=counts)
