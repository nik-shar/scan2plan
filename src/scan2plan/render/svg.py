"""Minimal SVG plan renderer (plan 04g, OUT-9).

Hand-rolled, dependency-free (the ``render`` extra with svgwrite/matplotlib is a
later convenience). Produces a single self-contained plan-view SVG: room boundary,
walls with dimension labels, openings legend, and the key measurements.
"""

from __future__ import annotations

import math
from pathlib import Path

from scan2plan.geometry.extract import RoomGeometry


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_room_svg(
    geom: RoomGeometry,
    out_path: Path,
    *,
    title: str = "scan2plan plan",
    scale_px_per_m: float = 90.0,
    margin: float = 90.0,
) -> Path:
    """Render the single-room plan to ``out_path`` and return the path."""
    boundary = geom.room.boundary
    walls = [s for s in geom.surfaces if s.type == "wall"]

    xs = [p[0] for p in boundary]
    zs = [p[1] for p in boundary]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    width_px = (maxx - minx) * scale_px_per_m + 2 * margin
    height_px = (maxz - minz) * scale_px_per_m + 2 * margin

    def px(p: list[float]) -> tuple[float, float]:
        return (
            margin + (p[0] - minx) * scale_px_per_m,
            margin + (maxz - p[1]) * scale_px_per_m,  # flip Y (SVG is y-down)
        )

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px:.0f}" height="{height_px:.0f}" '
        f'viewBox="0 0 {width_px:.0f} {height_px:.0f}" font-family="monospace">'
    )
    parts.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    parts.append(f'<text x="{margin:.0f}" y="32" font-size="18" fill="#111">{_esc(title)}</text>')

    # Room boundary (floor footprint).
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in (px(p) for p in boundary))
    parts.append(f'<polygon points="{poly}" fill="#eef3f7" stroke="#2a7" stroke-width="2"/>')

    # Walls as thick lines with length labels.
    for s in walls:
        (x0, y0), (x1, y1) = px(s.polygon[0]), px(s.polygon[1])
        parts.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
            f'stroke="#111" stroke-width="6"/>'
        )
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        length_m = math.hypot(x1 - x0, y1 - y0) / scale_px_per_m
        parts.append(
            f'<text x="{mx:.0f}" y="{my - 10:.0f}" font-size="13" fill="#003c8f" '
            f'text-anchor="middle">{length_m:.2f} m</text>'
        )

    # Measurements + openings legend (bottom margin).
    lines: list[str] = []
    if geom.room.floor_area is not None:
        fa = geom.room.floor_area
        lines.append(f"floor area: {fa.value:.2f} +/- {fa.half_width:.2f} m^2")
    if geom.room.ceiling_height is not None:
        ch = geom.room.ceiling_height
        lines.append(f"ceiling height: {ch.value:.2f} +/- {ch.half_width:.2f} m")
    for o in geom.openings:
        if o.width is not None:
            lines.append(
                f"{o.kind} ({o.id}): width {o.width.value:.2f} +/- {o.width.half_width:.2f} m"
            )
    if not geom.openings:
        lines.append("openings: none detected")
    for i, txt in enumerate(lines):
        parts.append(
            f'<text x="{margin:.0f}" y="{height_px - margin + 40 + 20 * i:.0f}" font-size="13" '
            f'fill="#333">{_esc(txt)}</text>'
        )

    parts.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n")
    return out_path
