"""Stage-1 evidence SVG renderer (plan 04i).

Only the observed-evidence layers are rendered here (wall cells, floor cells,
camera free-space, camera path). The plan/stage-2 renderers were moved to
``archive/old_stage23/render_plan_svg.py`` for the stage 2/3 redesign.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image, ImageDraw


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
