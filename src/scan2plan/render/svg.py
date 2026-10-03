"""SVG plan renderer (plan 04g/04i, OUT-9). Dependency-free, self-contained.

Fixes from plan 04i:
- canvas height includes the legend (the last door lines were clipped);
- openings are drawn as real **gaps** in the wall with a swing **arc**, not only
  as text, and every drawn opening is listed exactly once.
"""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw

from scan2plan.geometry.extract import RoomGeometry

_ORANGE = "#e07b00"
_GREY = "#9aa0a6"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _legend_lines(geom: RoomGeometry) -> list[str]:
    lines: list[str] = []
    if geom.room.floor_area is not None:
        fa = geom.room.floor_area
        lines.append(f"floor area: {fa.value:.2f} +/- {fa.half_width:.2f} m^2")
    if geom.room.ceiling_height is not None:
        ch = geom.room.ceiling_height
        lines.append(f"ceiling height: {ch.value:.2f} +/- {ch.half_width:.2f} m")
    for o in geom.openings:
        if o.width is not None:
            lines.append(f"{o.kind} ({o.id}): {o.width.value:.2f} +/- {o.width.half_width:.2f} m")
    if not geom.openings:
        lines.append("openings: none detected")
    return lines


def render_room_svg(
    geom: RoomGeometry,
    out_path: Path,
    *,
    title: str = "scan2plan plan",
    scale_px_per_m: float = 90.0,
    margin: float = 90.0,
) -> Path:
    """Render the single-room plan (walls as gaps + arcs, full legend) to ``out_path``."""
    boundary = geom.room.boundary
    walls = [s for s in geom.surfaces if s.type == "wall"]
    xs = [p[0] for p in boundary]
    zs = [p[1] for p in boundary]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    room_w = (maxx - minx) * scale_px_per_m
    room_h = (maxz - minz) * scale_px_per_m
    lines = _legend_lines(geom)
    legend_h = 50 + 20 * len(lines) + 20
    width_px = room_w + 2 * margin
    height_px = margin + room_h + legend_h  # fits all legend text (04i fix)

    def px(p: list[float]) -> tuple[float, float]:
        return (margin + (p[0] - minx) * scale_px_per_m, margin + (maxz - p[1]) * scale_px_per_m)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px:.0f}" height="{height_px:.0f}" '
        f'viewBox="0 0 {width_px:.0f} {height_px:.0f}" font-family="monospace">'
    )
    parts.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    parts.append(f'<text x="{margin:.0f}" y="32" font-size="18" fill="#111">{_esc(title)}</text>')
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in (px(p) for p in boundary))
    parts.append(f'<polygon points="{poly}" fill="#eef3f7" stroke="#2a7" stroke-width="2"/>')

    openings_by_surface: dict[str, list] = {}
    for o in geom.openings:
        openings_by_surface.setdefault(o.surface_id, []).append(o)

    for s in walls:
        _append_wall(parts, s, openings_by_surface.get(s.id, []), px, scale_px_per_m)

    for i, txt in enumerate(lines):
        parts.append(
            f'<text x="{margin:.0f}" y="{margin + room_h + 40 + 20 * i:.0f}" font-size="13" '
            f'fill="#333">{_esc(txt)}</text>'
        )
    parts.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n")
    return out_path


def _append_wall(parts: list[str], s, ops: list, px, scale_px_per_m: float) -> None:
    """Draw one wall: solid, or segmented with swing arcs for its openings."""
    (x0, y0), (x1, y1) = px(s.polygon[0]), px(s.polygon[1])
    wall_len = math.hypot(x1 - x0, y1 - y0)
    ux, uy = ((x1 - x0) / wall_len, (y1 - y0) / wall_len) if wall_len else (0.0, 0.0)
    gaps = [o.width.value * scale_px_per_m for o in ops if o.width is not None]
    if not gaps:
        parts.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
            f'stroke="#111" stroke-width="6"/>'
        )
    else:
        seg_len = max(0.0, (wall_len - sum(gaps)) / (len(gaps) + 1))
        cursor = 0.0
        for g in gaps:
            ax, ay = x0 + ux * cursor, y0 + uy * cursor
            bx, by = x0 + ux * (cursor + seg_len), y0 + uy * (cursor + seg_len)
            parts.append(
                f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
                f'stroke="#111" stroke-width="6"/>'
            )
            cursor += seg_len
            gx0, gy0 = x0 + ux * cursor, y0 + uy * cursor
            gx1, gy1 = x0 + ux * (cursor + g), y0 + uy * (cursor + g)
            parts.append(
                f'<path d="M {gx0:.1f} {gy0:.1f} A {g:.1f} {g:.1f} 0 0 1 {gx1:.1f} {gy1:.1f}" '
                f'fill="none" stroke="#003c8f" stroke-width="2"/>'
            )
            cursor += g
        parts.append(
            f'<line x1="{x0 + ux * cursor:.1f}" y1="{y0 + uy * cursor:.1f}" x2="{x1:.1f}" '
            f'y2="{y1:.1f}" stroke="#111" stroke-width="6"/>'
        )
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    parts.append(
        f'<text x="{mx:.0f}" y="{my - 10:.0f}" font-size="13" fill="#003c8f" '
        f'text-anchor="middle">{wall_len / scale_px_per_m:.2f} m</text>'
    )


def render_stage_svg(
    geom: RoomGeometry,
    regions: list[dict],
    out_path: Path,
    *,
    title: str = "scan2plan stages",
    scale_px_per_m: float = 90.0,
    margin: float = 90.0,
) -> Path:
    """Stage-2 diagnostic layer (plan 04i section 3).

    Walls solid black; removed items dashed grey with a short label; suspected
    occluders orange.
    """
    boundary = geom.room.boundary
    xs = [p[0] for p in boundary]
    zs = [p[1] for p in boundary]
    for r in regions:
        for p in r.get("polygon_xz", []):
            xs.append(p[0])
            zs.append(p[1])
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    room_w = (maxx - minx) * scale_px_per_m
    room_h = (maxz - minz) * scale_px_per_m
    width_px = room_w + 2 * margin
    height_px = margin + room_h + 80

    def px(p: list[float]) -> tuple[float, float]:
        return (margin + (p[0] - minx) * scale_px_per_m, margin + (maxz - p[1]) * scale_px_per_m)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px:.0f}" height="{height_px:.0f}" '
        f'viewBox="0 0 {width_px:.0f} {height_px:.0f}" font-family="monospace">'
    )
    parts.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    parts.append(f'<text x="{margin:.0f}" y="32" font-size="18" fill="#111">{_esc(title)}</text>')
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in (px(p) for p in boundary))
    parts.append(f'<polygon points="{poly}" fill="none" stroke="#111" stroke-width="5"/>')

    for r in regions:
        label = str(r.get("label", "?"))
        if label == "wall":
            continue
        color = _ORANGE if label == "suspected_occluder" else _GREY
        pts = r.get("polygon_xz", [])
        if len(pts) < 2:
            continue
        ring = " ".join(f"{x:.1f},{y:.1f}" for x, y in (px(p) for p in pts))
        parts.append(
            f'<polygon points="{ring}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-dasharray="5,4"/>'
        )
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        lx, ly = px([cx, cy])
        parts.append(
            f'<text x="{lx:.0f}" y="{ly:.0f}" font-size="11" fill="{color}" '
            f'text-anchor="middle">{_esc(label)}</text>'
        )
    legend = ["solid black = wall", "dashed grey = removed", "orange = suspected occluder"]
    for i, txt in enumerate(legend):
        parts.append(
            f'<text x="{margin:.0f}" y="{margin + room_h + 40 + 18 * i:.0f}" font-size="13" '
            f'fill="#333">{_esc(txt)}</text>'
        )
    parts.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n")
    return out_path


def render_outline_svg(
    polygon_xz: list[list[float]],
    out_path: Path,
    *,
    title: str = "scan2plan stage 1: observed outline",
    camera_xz: list[list[float]] | None = None,
    note: str | None = None,
    scale_px_per_m: float = 90.0,
    margin: float = 90.0,
) -> Path:
    """Stage-1 view: the observed outline of everything seen + the camera path.

    This is the "before" picture (furniture included, low-confidence depth already
    dropped), so it can be compared against the stage-3 plan.
    """
    xs = [p[0] for p in polygon_xz] or [0.0]
    zs = [p[1] for p in polygon_xz] or [0.0]
    if camera_xz:
        xs += [p[0] for p in camera_xz]
        zs += [p[1] for p in camera_xz]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    room_w = max((maxx - minx) * scale_px_per_m, 40.0)
    room_h = max((maxz - minz) * scale_px_per_m, 40.0)
    legend = [f"observed area: {_area(polygon_xz):.2f} m^2"]
    if camera_xz:
        legend.append(f"camera path: {len(camera_xz)} points")
    if note:
        legend.append(note)
    width_px = room_w + 2 * margin
    height_px = margin + room_h + 30 + 18 * len(legend)

    def px(p: list[float]) -> tuple[float, float]:
        return (margin + (p[0] - minx) * scale_px_per_m, margin + (maxz - p[1]) * scale_px_per_m)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px:.0f}" height="{height_px:.0f}" '
        f'viewBox="0 0 {width_px:.0f} {height_px:.0f}" font-family="monospace">'
    )
    parts.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    parts.append(f'<text x="{margin:.0f}" y="32" font-size="18" fill="#111">{_esc(title)}</text>')
    if polygon_xz:
        ring = " ".join(f"{x:.1f},{y:.1f}" for x, y in (px(p) for p in polygon_xz))
        parts.append(f'<polygon points="{ring}" fill="#fff4e6" stroke="#d9822b" stroke-width="3"/>')
    if camera_xz:
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in (px(p) for p in camera_xz))
        parts.append(f'<polyline points="{path}" fill="none" stroke="#1a73e8" stroke-width="2"/>')
    legend.insert(0, "orange = observed outline (all seen)")
    if camera_xz:
        legend.insert(1, "blue = camera path")
    for i, txt in enumerate(legend):
        parts.append(
            f'<text x="{margin:.0f}" y="{margin + room_h + 30 + 18 * i:.0f}" font-size="13" '
            f'fill="#333">{_esc(txt)}</text>'
        )
    parts.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n")
    return out_path


def _area(polygon_xz: list[list[float]]) -> float:
    if len(polygon_xz) < 3:
        return 0.0
    x = [p[0] for p in polygon_xz]
    z = [p[1] for p in polygon_xz]
    total = 0.0
    for i in range(len(x)):
        j = (i + 1) % len(x)
        total += x[i] * z[j] - x[j] * z[i]
    return abs(total) / 2.0


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
    """Stage-1 evidence layers (plan 04i): wall cells, floor cells, camera free-space.

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
    wall_cell_m = float(params.get("wall_cell_m", 0.02))

    coords = [_cell_xy(c) for c in list(wall) + list(floor) + list(free) + [list(p) for p in cam]]
    legend = [
        f"wall cells: {stage1.get('layer_counts', {}).get('wall_cells', len(wall))}",
        f"floor cells: {stage1.get('layer_counts', {}).get('floor_cells', len(floor))}",
        f"camera free-space: {stage1.get('layer_counts', {}).get('camera_free_space', len(free))}",
        f"bin {bin_m:.2f} m | camera travel {stage1.get('camera_travel_m')} m",
    ]
    stats = stage1.get("statistics", {})
    if isinstance(stats, dict) and stats.get("camera_inside_fraction") is not None:
        legend.append(f"camera inside evidence: {stats['camera_inside_fraction']:.0%}")

    if not coords:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="120">'
            f'<rect width="100%" height="100%" fill="#fff"/>'
            f'<text x="20" y="40" font-size="16">{_esc(title)}</text>'
            f'<text x="20" y="70" font-size="13">no observed evidence</text></svg>\n'
        )
        return out_path

    xs = [c[0] for c in coords]
    zs = [c[1] for c in coords]
    pad = 0.5
    bx0, bz1 = min(xs) - pad, max(zs) + pad
    w_m = (max(xs) - min(xs)) + 2 * pad
    h_m = (max(zs) - min(zs)) + 2 * pad
    w_px = max(40, int(w_m * px_per_m))
    h_px = max(40, int(h_m * px_per_m))
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
