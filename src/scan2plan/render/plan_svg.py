"""Final plan renderer (stage 3, OUT-9): rooms, walls, openings, scale bar (plan 04g).

Self-contained SVG (one file, no external assets). Observed walls are solid, inferred
pieces are dashed with a distinct dash per provenance, openings are drawn as arcs,
each room carries an area label with its interval, unobserved-enclosed areas are
hatched, and a scale bar is included. The canvas height fits the legend so no text is
clipped.
"""

from __future__ import annotations

from pathlib import Path

from scan2plan.render.svg import clipped_wall_lines
from scan2plan.util.logging import get_logger

logger = get_logger("scan2plan.render.plan_svg")


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _collect_pts(stage3: dict) -> tuple[list[float], list[float]]:
    """World x/z extents across rooms, unobserved polygons and opening endpoints."""
    xs: list[float] = []
    zs: list[float] = []

    def add(pt: list[float]) -> None:
        xs.append(float(pt[0]))
        zs.append(float(pt[1]))

    for r in stage3.get("rooms", []) or []:
        for p in r.get("polygon_world", []):
            add(p)
    for e in stage3.get("unobserved_enclosed", []) or []:
        for p in e.get("polygon_world", []):
            add(p)
    for o in stage3.get("openings", []) or []:
        ep = o.get("endpoints_world")
        if ep:
            add(ep["a"])
            add(ep["b"])
    return xs, zs


def render_plan_svg(
    stage3: dict,
    out_path: Path,
    *,
    stage2: dict | None = None,
    title: str = "scan2plan final plan",
    px_per_m: float = 80.0,
    margin: float = 90.0,
) -> Path:
    """Render the final dimensioned plan (rooms, walls, openings, scale bar).

    Walls are drawn only as clipped segments of their stage-2 graph edges (observed
    solid, inferred dashed), so no wall line runs past the node it ends at.
    """
    rooms = stage3.get("rooms", []) or []
    enclosed = stage3.get("unobserved_enclosed", []) or []
    openings = stage3.get("openings", []) or []
    xs, zs = _collect_pts(stage3)
    if not xs:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="420" height="140">'
            '<rect width="100%" height="100%" fill="#fff"/>'
            f'<text x="20" y="40" font-size="16">{_esc(title)}</text>'
            '<text x="20" y="72" font-size="13">no rooms computed</text></svg>\n'
        )
        return out_path

    pad = 0.6
    x0, z1 = min(xs) - pad, max(zs) + pad
    w_px = max(60.0, (max(xs) - min(xs) + 2 * pad) * px_per_m)
    h_px = max(60.0, (max(zs) - min(zs) + 2 * pad) * px_per_m)

    def pix(x: float, z: float) -> tuple[float, float]:
        return ((x - x0) * px_per_m, (z1 - z) * px_per_m)

    legend = [
        f"rooms: {len(rooms)} | unobserved_enclosed: {len(enclosed)} | openings: {len(openings)}",
        f"plan_score {stage3.get('plan_score')} | closures {stage3.get('closure_counts')}",
        "walls: observed solid | inferred dashed (extension 10-4, occluded 6-3, closure 3-3)",
        "openings: green arc | unobserved areas: hatched grey",
        f"scale: 1 m = {px_per_m:.0f} px",
    ]
    out_w = w_px + 2 * margin
    out_h = h_px + margin + 40 + 18 * (len(legend) + len(rooms))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{out_w:.0f}" height="{out_h:.0f}" '
        f'viewBox="0 0 {out_w:.0f} {out_h:.0f}" font-family="monospace">',
        '<defs><pattern id="hatch" width="8" height="8" patternTransform="rotate(45)" '
        'patternUnits="userSpaceOnUse"><line x1="0" y1="0" x2="0" y2="8" '
        'stroke="#bbb" stroke-width="2"/></pattern></defs>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin:.0f}" y="30" font-size="17" fill="#111">{_esc(title)}</text>',
        f'<g transform="translate({margin:.0f},{margin:.0f})">',
    ]

    for e in enclosed:
        pts = " ".join(f"{pix(*p)[0]:.1f},{pix(*p)[1]:.1f}" for p in e.get("polygon_world", []))
        if pts:
            parts.append(
                f'<polygon points="{pts}" fill="url(#hatch)" stroke="#999" stroke-width="1"/>'
            )
    for r in rooms:
        pts = " ".join(f"{pix(*p)[0]:.1f},{pix(*p)[1]:.1f}" for p in r.get("polygon_world", []))
        if pts:
            parts.append(
                f'<polygon points="{pts}" fill="#f4f7ff" stroke="#3457d5" stroke-width="2"/>'
            )
        c = r.get("polygon_world", [])
        if c:
            cx = sum(p[0] for p in c) / len(c)
            cz = sum(p[1] for p in c) / len(c)
            px, py = pix(cx, cz)
            a = r.get("area", {})
            parts.append(
                f'<text x="{px:.1f}" y="{py:.1f}" font-size="12" text-anchor="middle" '
                f'fill="#123">{_esc(str(r.get("id")))} {a.get("value")} m2</text>'
            )
    for o in openings:
        ep = o.get("endpoints_world")
        if ep:
            (ax, ay), (bx, by) = pix(*ep["a"]), pix(*ep["b"])
            parts.append(
                f'<path d="M {ax:.1f} {ay:.1f} A 12 12 0 0 1 {bx:.1f} {by:.1f}" '
                'fill="none" stroke="#28a745" stroke-width="2"/>'
            )
    if stage2 is not None:
        for a_w, b_w, prov in clipped_wall_lines(stage2):
            (ax, ay), (bx, by) = pix(*a_w), pix(*b_w)
            if prov == "observed":
                parts.append(
                    f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
                    'stroke="#111" stroke-width="2"/>'
                )
            else:
                parts.append(
                    f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
                    'stroke="#c25a12" stroke-width="2" stroke-dasharray="8 4"/>'
                )
    parts.append("</g>")

    bar_y = margin + h_px + 12
    parts.append(
        f'<line x1="{margin:.0f}" y1="{bar_y:.0f}" x2="{margin + px_per_m:.0f}" '
        f'y2="{bar_y:.0f}" stroke="#000" stroke-width="3"/>'
    )
    parts.append(
        f'<text x="{margin:.0f}" y="{bar_y + 16:.0f}" font-size="12" fill="#333">1 m</text>'
    )
    for i, txt in enumerate(legend):
        parts.append(
            f'<text x="{margin:.0f}" y="{bar_y + 36 + 18 * i:.0f}" font-size="13" '
            f'fill="#333">{_esc(txt)}</text>'
        )
    row = bar_y + 36 + 18 * len(legend)
    for r in rooms:
        a = r.get("area", {})
        ceil = r.get("ceiling", {})
        parts.append(
            f'<text x="{margin:.0f}" y="{row:.0f}" font-size="12" fill="#333">'
            f"{_esc(str(r.get('id')))}: area {a.get('value')} m2 "
            f"[{a.get('ci_low')}, {a.get('ci_high')}] | perimeter observed "
            f"{r.get('perimeter', {}).get('observed_frac')} | ceiling "
            f"{ceil.get('value')} ({ceil.get('status')})</text>"
        )
        row += 18
    parts.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n")
    return out_path
