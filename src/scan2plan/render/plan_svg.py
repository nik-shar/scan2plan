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
from scan2plan.stitch.se2 import apply
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


#: Damage-class tint for the plan overlay (plan 04e / 04g section 3).
DAMAGE_COLORS: dict[str, str] = {
    "crack": "#c62828",
    "water_stain": "#8d6e00",
    "mold": "#2e7d32",
    "spalling": "#8d6e63",
    "paint_peel": "#1565c0",
    "rot": "#4e342e",
}


def _damage_overlays(
    surfaces: list | None, damages: list | None
) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
    """World segments (a, b, class) for each damage, keyed via its host surface.

    A damage polygon is in the surface frame ``(along-wall m, height m)``; its
    along-range is projected back onto the wall's world 2-point polygon.
    """
    if not surfaces or not damages:
        return []
    by_id = {s.id: s for s in surfaces}
    out: list[tuple[tuple[float, float], tuple[float, float], str]] = []
    for dmg in damages:
        surf = by_id.get(dmg.surface_id)
        if surf is None or len(surf.polygon) < 2 or len(dmg.polygon) < 2:
            continue
        ax, az = float(surf.polygon[0][0]), float(surf.polygon[0][1])
        bx, bz = float(surf.polygon[1][0]), float(surf.polygon[1][1])
        dx, dz = bx - ax, bz - az
        length = (dx * dx + dz * dz) ** 0.5
        if length < 1e-9:
            continue
        tx, tz = dx / length, dz / length
        s0 = min(float(dmg.polygon[0][0]), float(dmg.polygon[2][0]))
        s1 = max(float(dmg.polygon[0][0]), float(dmg.polygon[2][0]))
        s0, s1 = max(0.0, s0), min(length, s1)
        out.append(((ax + s0 * tx, az + s0 * tz), (ax + s1 * tx, az + s1 * tz), str(dmg.cls)))
    return out


def render_plan_svg(
    stage3: dict,
    out_path: Path,
    *,
    stage2: dict | None = None,
    title: str = "scan2plan final plan",
    damages: list | None = None,
    surfaces: list | None = None,
    concealed: list | None = None,
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
    if damages:
        counts: dict[str, int] = {}
        for dmg in damages:
            counts[str(dmg.cls)] = counts.get(str(dmg.cls), 0) + 1
        legend.append("damage: " + ", ".join(f"{k} x{v}" for k, v in sorted(counts.items())))
    if concealed:
        legend.append(f"concealed flags: {len(concealed)} (ringed, dashed)")
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
    concealed_surfaces = {c.surface_id for c in (concealed or [])}
    for a_w, b_w, cls in _damage_overlays(surfaces, damages):
        (ax, ay), (bx, by) = pix(*a_w), pix(*b_w)
        color = DAMAGE_COLORS.get(cls, "#444")
        parts.append(
            f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
            f'stroke="{color}" stroke-width="6" stroke-linecap="round" opacity="0.75"/>'
        )
    for dmg in damages or []:
        if dmg.surface_id not in concealed_surfaces or len(dmg.polygon) < 2:
            continue
        surf = next((s for s in (surfaces or []) if s.id == dmg.surface_id), None)
        if surf is None or len(surf.polygon) < 2:
            continue
        ax, az = float(surf.polygon[0][0]), float(surf.polygon[0][1])
        bx, bz = float(surf.polygon[1][0]), float(surf.polygon[1][1])
        dx, dz = bx - ax, bz - az
        length = (dx * dx + dz * dz) ** 0.5 or 1.0
        mid_s = 0.5 * (float(dmg.polygon[0][0]) + float(dmg.polygon[2][0]))
        mx, mz = ax + mid_s * dx / length, az + mid_s * dz / length
        cx, cy = pix(mx, mz)
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="7" fill="none" '
            'stroke="#000" stroke-width="2" stroke-dasharray="3 2"/>'
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


def render_ablation_svg(
    stage3: dict,
    transforms: dict,
    ablation: object,
    out_path: Path,
    *,
    title: str = "scan2plan drift ablation (G-DRIFT)",
    px_per_m: float = 60.0,
    margin: float = 70.0,
) -> Path:
    """Render the loop-closure on/off footprints side by side (plan 04d section 4)."""
    rooms = stage3.get("rooms") or []
    panels = [
        ("loop closure ON", transforms.get("on", {})),
        ("OFF (poses as-is)", transforms.get("off", {})),
    ]

    def place(t: object, x: float, y: float) -> tuple[float, float]:
        return apply(t, x, y) if t is not None else (x, y)  # type: ignore[arg-type]

    pts_by_panel: list[list[tuple[float, float]]] = []
    for _label, tf in panels:
        pts: list[tuple[float, float]] = []
        for r in rooms:
            t = tf.get(r["id"])
            for p in r.get("polygon_world") or []:
                pts.append(place(t, float(p[0]), float(p[1])))
        pts_by_panel.append(pts)
    all_pts = [p for pts in pts_by_panel for p in pts]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not all_pts:
        out_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="420" height="140">'
            '<rect width="100%" height="100%" fill="#fff"/>'
            f'<text x="20" y="40" font-size="16">{_esc(title)}</text>'
            '<text x="20" y="72" font-size="13">no rooms to ablate</text></svg>\n'
        )
        return out_path

    pad = 0.5
    minx = min(p[0] for p in all_pts) - pad
    maxx = max(p[0] for p in all_pts) + pad
    miny = min(p[1] for p in all_pts) - pad
    maxy = max(p[1] for p in all_pts) + pad
    pw = max(60.0, (maxx - minx) * px_per_m)
    ph = max(60.0, (maxy - miny) * px_per_m)
    on_fp = getattr(getattr(ablation, "loop_closure_on", None), "footprint_m2", None)
    off_fp = getattr(getattr(ablation, "off", None), "footprint_m2", None)
    gap = getattr(getattr(ablation, "loop_closure_on", None), "closure_gap_m", None)
    legend = [
        f"on footprint {on_fp} m2 | off footprint {off_fp} m2 | closure gap {gap} m",
        "same code path; only loop-closure constraints differ (plan 04d section 4)",
        f"scale: 1 m = {px_per_m:.0f} px",
    ]
    out_w = 2 * pw + 3 * margin
    out_h = ph + margin + 60 + 18 * len(legend)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{out_w:.0f}" height="{out_h:.0f}" '
        f'viewBox="0 0 {out_w:.0f} {out_h:.0f}" font-family="monospace">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin:.0f}" y="30" font-size="17" fill="#111">{_esc(title)}</text>',
    ]
    for k, (label, _tf) in enumerate(panels):
        ox = margin + k * (pw + margin)
        fill = "#eef3ff" if k == 0 else "#fff1ee"
        stroke = "#3457d5" if k == 0 else "#c25a12"
        parts.append(f'<text x="{ox:.0f}" y="{margin - 8:.0f}" font-size="13">{_esc(label)}</text>')
        for r in rooms:
            t = panels[k][1].get(r["id"])
            poly = [place(t, float(p[0]), float(p[1])) for p in r.get("polygon_world") or []]
            if not poly:
                continue
            sp = " ".join(
                f"{ox + (x - minx) * px_per_m:.1f},{(maxy - y) * px_per_m + margin:.1f}"
                for x, y in poly
            )
            parts.append(
                f'<polygon points="{sp}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
            )
    for i, txt in enumerate(legend):
        parts.append(
            f'<text x="{margin:.0f}" y="{margin + ph + 30 + 18 * i:.0f}" font-size="13" '
            f'fill="#333">{_esc(txt)}</text>'
        )
    parts.append("</svg>")
    out_path.write_text("\n".join(parts) + "\n")
    return out_path
