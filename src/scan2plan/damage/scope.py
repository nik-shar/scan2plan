"""Scope line items keyed to surfaces (plan 04e section 4, OUT-5).

Each damage maps to a repair task with a **quantity as a Measurement** (I6): a
crack is linear (metres), the area-like classes are square metres. The interval
is the damage extent interval (``extent_rel_ci``) until 04f calibrates it, so a
scope quantity is never a bare float and never a false precision.
"""

from __future__ import annotations

from scan2plan.cir import Damage, Measurement, ScopeItem, Tier
from scan2plan.config import Config

#: damage class -> (task, unit).
TASK: dict[str, tuple[str, str]] = {
    "crack": ("seal/patch crack", "m"),
    "water_stain": ("treat + repaint", "m2"),
    "mold": ("remediate", "m2"),
    "spalling": ("re-plaster", "m2"),
    "paint_peel": ("scrape + repaint", "m2"),
    "rot": ("treat/replace timber", "m2"),
}


def scope_items(damages: list[Damage], cfg: Config, tier: Tier = "lidar") -> list[ScopeItem]:
    """Map every damage to a surface-keyed repair line item."""
    rel = cfg.damage.extent_rel_ci
    out: list[ScopeItem] = []
    for dmg in damages:
        spec = TASK.get(dmg.cls)
        if spec is None:
            continue
        task, unit = spec
        bbox = dmg.extent.bbox_m or [0.0, 0.0]
        if unit == "m":
            value = max(float(bbox[0]), float(bbox[1]))
        else:
            value = float(dmg.extent.area_m2 or 0.0)
        if value <= 0.0:
            continue
        lo, hi = value * (1.0 - rel), value * (1.0 + rel)
        qty = Measurement(
            id=f"{dmg.id}.qty",
            kind="damage_quantity",
            value=round(value, 4),
            unit=unit,
            ci_low=round(lo, 4),
            ci_high=round(hi, 4),
            method="damage_extent",
            tier=tier,
        )
        out.append(
            ScopeItem(
                id=f"scope_{dmg.id}",
                surface_id=dmg.surface_id,
                task=task,
                quantity=qty,
            )
        )
    return out
