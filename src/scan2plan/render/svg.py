"""SVG plan renderer (plan 04g/04i, OUT-9). Dependency-free, self-contained.

Fixes from plan 04i:
- canvas height includes the legend (the last door lines were clipped);
- openings are drawn as real **gaps** in the wall with a swing **arc**, not only
  as text, and every drawn opening is listed exactly once.
"""

from __future__ import annotations

import math
from pathlib import Path

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
