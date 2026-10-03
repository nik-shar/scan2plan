"""Stage-1 evidence SVG renderer (plan 04i).

Only the observed-evidence layers are rendered here (wall cells, floor cells,
camera free-space, camera path). The plan/stage-2 renderers were moved to
``archive/old_stage23/render_plan_svg.py`` for the stage 2/3 redesign.
"""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from scan2plan.geometry.rooms import uv_to_world
from scan2plan.geometry.walls import (
    dense_blob_mask,
    explained_mask,
    rotate_xz,
    segments_from_payload,
)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clipped_wall_lines(stage2: dict) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
    """Wall lines to draw, clipped to their graph nodes (world xz + provenance).

    Each stage-2 segment is clipped to the extent of the graph nodes on its wall
    line (``node_tol_m``/``collinear_tol_m``), so a drawn wall never extends beyond
    the node it ends at (invariant ``render_clip``). Segments with no line nodes are
    kept as-is (nothing to clip to).
    """
    params = stage2.get("params", {})
    line_tol = max(
        float(params.get("node_tol_m", 0.05)), float(params.get("collinear_tol_m", 0.15))
    )
    theta = math.radians(float(stage2.get("manhattan_angle_deg", 0.0) or 0.0))
    graph = stage2.get("graph") or {}
    nodes_uv = [(float(n["uv"][0]), float(n["uv"][1])) for n in (graph.get("nodes") or [])]
    out: list[tuple[tuple[float, float], tuple[float, float], str]] = []
    for s in stage2.get("segments", []) or []:
        axis = 0 if s.get("axis") == "u" else 1
        off = float(s.get("offset_m", 0.0))
        lo, hi = float(s.get("start_m", 0.0)), float(s.get("end_m", 0.0))
        perp = [u if axis == 0 else v for u, v in nodes_uv]
        along = [v if axis == 0 else u for u, v in nodes_uv]
        line = sorted(a for p, a in zip(perp, along, strict=True) if abs(p - off) <= line_tol)
        if line:
            lo, hi = max(lo, line[0]), min(hi, line[-1])
        if hi - lo <= 1e-6:
            continue
        a_uv = (off, lo) if axis == 0 else (lo, off)
        b_uv = (off, hi) if axis == 0 else (hi, off)
        out.append(
            (
                uv_to_world(a_uv[0], a_uv[1], theta),
                uv_to_world(b_uv[0], b_uv[1], theta),
                str(s.get("provenance", "observed")),
            )
        )
    return out


def _cell_xy(c: object) -> tuple[float, float]:
    """Accept a wall cell (dict with x/z) or a [x, z] pair."""
    if isinstance(c, dict):
        return float(c["x"]), float(c["z"])
    assert isinstance(c, list)
    return float(c[0]), float(c[1])


def render_evidence_svg(
    stage1: dict,
    out_path: Path,
    *,
    title: str = "scan2plan stage 1: observed evidence",
    px_per_m: float = 90.0,
    margin: float = 80.0,
) -> Path:
    """Stage-1 evidence layers: wall cells, floor cells, camera free-space.

    Rendered as an embedded PNG so thousands of cells stay compact; unknown area
    stays blank. The camera path is drawn on top. Nothing is hulled/buffered.
    """
    layers = stage1.get("layers", {})
    wall = layers.get("wall_cells", [])
    floor = layers.get("floor_cells", [])
    free = layers.get("camera_free_space", [])
    cam = stage1.get("camera_xz", [])
    params = stage1.get("params", {})
    bin_m = float(params.get("evidence_bin_m", 0.10))
    wall_cell_m = float(params.get("cell_m", 0.02))
    counts = stage1.get("layer_counts", {})
    legend = [
        f"wall cells: {counts.get('wall_cells', len(wall))}",
        f"floor cells: {counts.get('floor_cells', len(floor))}",
        f"camera free-space: {counts.get('camera_free_space', len(free))}",
        f"bin {bin_m:.2f} m | camera travel {stage1.get('camera_travel_m')} m",
    ]
    stats = stage1.get("statistics", {})
    if isinstance(stats, dict) and stats.get("camera_inside_fraction") is not None:
        legend.append(f"camera inside evidence: {stats['camera_inside_fraction']:.0%}")

    coords = [_cell_xy(c) for c in list(wall) + list(floor) + list(free) + [list(p) for p in cam]]
    if not coords:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="120">'
            '<rect width="100%" height="100%" fill="#fff"/>'
            f'<text x="20" y="40" font-size="16">{_esc(title)}</text>'
            '<text x="20" y="70" font-size="13">no observed evidence</text></svg>\n'
        )
        return out_path

    xs = [c[0] for c in coords]
    zs = [c[1] for c in coords]
    pad = 0.5
    bx0, bz1 = min(xs) - pad, max(zs) + pad
    w_px = max(40, int(((max(xs) - min(xs)) + 2 * pad) * px_per_m))
    h_px = max(40, int(((max(zs) - min(zs)) + 2 * pad) * px_per_m))
    img = Image.new("RGB", (w_px, h_px), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    def pix(x: float, z: float) -> tuple[float, float]:
        return ((x - bx0) * px_per_m, (bz1 - z) * px_per_m)  # flip z (SVG is y-down)

    def sq(x: float, z: float, size_px: float, fill: tuple[int, int, int]) -> None:
        cx, cy = pix(x, z)
        h = size_px / 2
        draw.rectangle([cx - h, cy - h, cx + h, cy + h], fill=fill)

    bin_px = max(1.0, bin_m * px_per_m)
    wall_px = max(1.0, wall_cell_m * px_per_m)
    for c in floor:
        sq(*_cell_xy(c), bin_px, (219, 234, 254))  # light blue = observed floor
    for c in free:
        sq(*_cell_xy(c), bin_px, (222, 252, 231))  # light green = camera free-space
    for c in wall:
        support = int(c.get("support", 1)) if isinstance(c, dict) else 1
        shade = max(80, 210 - 15 * support)
        sq(*_cell_xy(c), wall_px, (shade, shade, shade))  # grey, darker = more support
    path_px = [pix(*_cell_xy(p)) for p in cam]
    if len(path_px) > 1:
        draw.line(path_px, fill=(26, 115, 232), width=2)  # blue camera path
    # stage-1 addition: mark the path start (green) and end (red).
    for pt, colour in (
        (stage1.get("camera_start"), (46, 160, 67)),
        (stage1.get("camera_end"), (217, 48, 37)),
    ):
        if pt:
            cx, cy = pix(float(pt[0]), float(pt[1]))
            draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=colour)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    out_w = w_px + 2 * margin
    out_h = h_px + margin + 30 + 18 * len(legend)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{out_w:.0f}" height="{out_h:.0f}" '
        f'viewBox="0 0 {out_w:.0f} {out_h:.0f}" font-family="monospace">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin:.0f}" y="30" font-size="17" fill="#111">{_esc(title)}</text>',
        f'<image x="{margin:.0f}" y="{margin:.0f}" width="{w_px}" height="{h_px}" '
        f'href="data:image/png;base64,{b64}"/>',
    ]
    for i, txt in enumerate(legend):
        parts.append(
            f'<text x="{margin:.0f}" y="{margin + h_px + 30 + 18 * i:.0f}" font-size="13" '
            f'fill="#333">{_esc(txt)}</text>'
        )
    parts.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n")
    return out_path


def render_walls_svg(
    stage2: dict,
    out_path: Path,
    *,
    stage1: dict | None = None,
    title: str = "scan2plan stage 2: wall reconstruction",
    px_per_m: float = 90.0,
    margin: float = 80.0,
) -> Path:
    """Stage-2 wall reconstruction: kept/dropped cells + the fitted wall lines.

    Wall cells are shaded by height-bin support (dark = kept, faded = dropped by
    the support gate); the four reconstructed wall segments are drawn as bold red
    lines. Rendered as an embedded PNG so thousands of cells stay compact.
    """
    segs = stage2.get("segments", [])
    params = stage2.get("params", {})
    tol = float(params.get("evidence_tol_m", 0.05))
    theta = math.radians(float(stage2.get("manhattan_angle_deg", 0.0)))
    cells = []
    if isinstance(stage1, dict):
        cells = stage1.get("layers", {}).get("wall_cells", []) or []

    coords: list[tuple[float, float]] = [(float(c["x"]), float(c["z"])) for c in cells]
    for s in segs:
        ep = s.get("endpoints_world")
        if ep:
            coords.append((float(ep["a"][0]), float(ep["a"][1])))
            coords.append((float(ep["b"][0]), float(ep["b"][1])))
    if isinstance(stage1, dict):
        for pt in (stage1.get("camera_start"), stage1.get("camera_end")):
            if pt:
                coords.append((float(pt[0]), float(pt[1])))

    if not coords:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="120">'
            '<rect width="100%" height="100%" fill="#fff"/>'
            f'<text x="20" y="40" font-size="16">{_esc(title)}</text>'
            '<text x="20" y="70" font-size="13">no wall cells</text></svg>\n'
        )
        return out_path

    xs = [c[0] for c in coords]
    zs = [c[1] for c in coords]
    pad = 0.5
    bx0, bz1 = min(xs) - pad, max(zs) + pad
    w_px = max(40, int(((max(xs) - min(xs)) + 2 * pad) * px_per_m))
    h_px = max(40, int(((max(zs) - min(zs)) + 2 * pad) * px_per_m))
    img = Image.new("RGB", (w_px, h_px), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    def pix(x: float, z: float) -> tuple[float, float]:
        return ((x - bx0) * px_per_m, (bz1 - z) * px_per_m)

    def sq(x: float, z: float, size_px: float, fill: tuple[int, int, int]) -> None:
        cx, cy = pix(x, z)
        h = size_px / 2
        draw.rectangle([cx - h, cy - h, cx + h, cy + h], fill=fill)

    cell_xz = (
        np.array([[float(c["x"]), float(c["z"])] for c in cells], dtype=np.float64)
        if cells
        else np.empty((0, 2), dtype=np.float64)
    )
    uv = rotate_xz(cell_xz, theta) if cells else cell_xz
    explained = (
        explained_mask(uv, segments_from_payload(stage2), tol) if cells else np.zeros(0, dtype=bool)
    )
    dense = (
        dense_blob_mask(
            uv,
            ~explained,
            float(params.get("blob_bin_m", 0.10)),
            int(params.get("blob_min_cells", 6)),
        )
        if cells
        else np.zeros(0, dtype=bool)
    )
    cell_px = max(1.0, float(params.get("cell_m", 0.02)) * px_per_m)
    for c, seen, blob in zip(cells, explained, dense, strict=True):
        if seen:
            support = int(c.get("support", 1))
            shade = max(80, 210 - 14 * support)
            colour = (shade, shade, shade)  # wall-like (explained)
        elif blob:
            colour = (214, 124, 40)  # dense blob (furniture / occluder)
        else:
            colour = (232, 168, 160)  # residual noise
        sq(float(c["x"]), float(c["z"]), cell_px, colour)
    for a_w, b_w, prov in clipped_wall_lines(stage2):
        line_colour = (230, 120, 20) if prov != "observed" else (30, 80, 220)
        draw.line([pix(a_w[0], a_w[1]), pix(b_w[0], b_w[1])], fill=line_colour, width=3)
    for o in stage2.get("openings", []) or []:
        ep = o.get("endpoints_world")
        if ep:
            draw.line(
                [
                    pix(float(ep["a"][0]), float(ep["a"][1])),
                    pix(float(ep["b"][0]), float(ep["b"][1])),
                ],
                fill=(30, 170, 90),  # openings the camera walked through (doors)
                width=4,
            )
    for u in stage2.get("unknown_gaps", []) or []:
        ep = u.get("endpoints_world")
        if ep:
            draw.line(
                [
                    pix(float(ep["a"][0]), float(ep["a"][1])),
                    pix(float(ep["b"][0]), float(ep["b"][1])),
                ],
                fill=(150, 60, 200),  # unresolved evidence-free gaps (flagged)
                width=3,
            )
    for u in stage2.get("open_spaces", []) or []:
        ep = u.get("endpoints_world")
        if ep:
            draw.line(
                [
                    pix(float(ep["a"][0]), float(ep["a"][1])),
                    pix(float(ep["b"][0]), float(ep["b"][1])),
                ],
                fill=(0, 150, 180),  # wide camera-crossed gap (open space, walk-through)
                width=4,
            )
    g = stage2.get("graph", {})
    for node in g.get("nodes", []) or []:
        w = node.get("world")
        if not w:
            continue
        cx, cy = pix(float(w[0]), float(w[1]))
        ntype = node.get("type")
        if ntype == "L":  # circle
            draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], outline=(20, 20, 20), width=2)
        elif ntype == "T":  # square
            draw.rectangle([cx - 4, cy - 4, cx + 4, cy + 4], outline=(20, 20, 20), width=2)
        elif ntype == "cross":  # diamond
            draw.polygon(
                [(cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)],
                outline=(20, 20, 20),
            )
        else:  # dangling end -> red ring
            draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=(217, 48, 37), width=2)
    if isinstance(stage1, dict):
        path = stage1.get("camera_xz", []) or []
        path_px = [pix(float(p[0]), float(p[1])) for p in path]
        if len(path_px) > 1:
            draw.line(path_px, fill=(26, 115, 232), width=2)
        for pt, marker in (
            (stage1.get("camera_start"), (46, 160, 67)),
            (stage1.get("camera_end"), (217, 48, 37)),
        ):
            if pt:
                cx, cy = pix(float(pt[0]), float(pt[1]))
                draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=marker)

    ev = stage2.get("evidence", {})
    comp = stage2.get("completion", {})
    ln = stage2.get("lengths", {})
    mr = stage2.get("merge", {})
    nc = stage2.get("node_counts", {}) or g.get("counts", {})
    legend = [
        f"wall segments: {stage2.get('wall_count')} "
        f"(observed {stage2.get('observed_count')}, inferred {stage2.get('inferred_count')})",
        f"length: observed {ln.get('observed_length_m')} m, "
        f"inferred {ln.get('inferred_length_m')} m | longest inferred run "
        f"{ln.get('longest_inferred_run_m')} m (> max_extend "
        f"{ln.get('inferred_runs_over_max_extend')})",
        f"evidence: wall_like {ev.get('wall_like_explained')} ({ev.get('wall_like_frac')}), "
        f"dense_blobs {ev.get('dense_blobs')} ({ev.get('dense_blob_frac')}), "
        f"residual_noise {ev.get('residual_noise')} ({ev.get('residual_noise_frac')})",
        f"evidence_explained: {ev.get('evidence_explained')} "
        f"(kept {ev.get('evidence_explained_kept')})",
        f"openings: {len(stage2.get('openings') or [])} (green, 0.5-2.5 m) | "
        f"open_space: {len(stage2.get('open_spaces') or [])} (teal, >2.5 m) | "
        f"unknown gaps: {len(stage2.get('unknown_gaps') or [])} (purple)",
        f"completion: occluded {comp.get('bridged_occluded')}, "
        f"dropout {comp.get('bridged_dropout')}, extended {comp.get('extended')}",
        "cells: wall_like grey | dense blob orange | residual noise pale red",
        f"merge: walls {mr.get('segments_before')}->{mr.get('segments_after')} "
        f"({mr.get('thick_walls')} thick) | nodes {mr.get('nodes_before')}->"
        f"{mr.get('nodes_after')}",
        f"nodes: L {nc.get('L')} o, T {nc.get('T')} [], cross {nc.get('cross')} <> "
        f"(was {mr.get('crosses_before')}), dangling {len(g.get('dangling_ends') or [])} red ring",
        f"angle {stage2.get('manhattan_angle_deg')} deg | min run {params.get('min_run_m')} m "
        f"| merge tol {params.get('merge_tol_m')} m | node merge {params.get('node_merge_m')} m",
        "camera start (green) / end (red)",
    ]

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    out_w = w_px + 2 * margin
    out_h = h_px + margin + 30 + 18 * len(legend)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{out_w:.0f}" height="{out_h:.0f}" '
        f'viewBox="0 0 {out_w:.0f} {out_h:.0f}" font-family="monospace">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin:.0f}" y="30" font-size="17" fill="#111">{_esc(title)}</text>',
        f'<image x="{margin:.0f}" y="{margin:.0f}" width="{w_px}" height="{h_px}" '
        f'href="data:image/png;base64,{b64}"/>',
    ]
    for i, txt in enumerate(legend):
        parts.append(
            f'<text x="{margin:.0f}" y="{margin + h_px + 30 + 18 * i:.0f}" font-size="13" '
            f'fill="#333">{_esc(txt)}</text>'
        )
    parts.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n")
    return out_path
