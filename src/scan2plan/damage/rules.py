"""Concealed-damage rule engine (plan 04e section 3, OUT-4).

A small, versioned, deterministic rule set: each rule has an id, human text,
the inputs it used, and the surface it fires on. The **id that fired** is emitted
verbatim on the :class:`scan2plan.cir.ConcealedFlag` so the report can explain
every concealed call (the brief's OUT-4 requirement).
"""

from __future__ import annotations

from scan2plan.cir import ConcealedFlag, Damage
from scan2plan.config import Config

#: rule_id -> (human text, unit of the gated input).
RULE_TEXT: dict[str, str] = {
    "R-CONCEAL-MOIST-01": (
        "water_stain/mold area above threshold on an interior wall -> concealed moisture"
    ),
    "R-CONCEAL-STRUCT-01": (
        "crack length above threshold on a wall -> concealed structural movement"
    ),
    "R-CONCEAL-BIO-01": "mold cluster area above threshold -> concealed biological growth",
}


def concealed_flags(
    damages: list[Damage],
    cfg: Config,
    *,
    evidence_ref: str = "damage.json",
) -> list[ConcealedFlag]:
    """Evaluate every rule against every damage; emit the flags that fired."""
    d = cfg.damage
    out: list[ConcealedFlag] = []
    for dmg in damages:
        area = float(dmg.extent.area_m2 or 0.0)
        bbox = dmg.extent.bbox_m or [0.0, 0.0]
        length = max(float(bbox[0]), float(bbox[1]))
        inputs = {"area_m2": round(area, 4), "length_m": round(length, 4)}
        if dmg.cls in ("water_stain", "mold") and area > d.moisture_area_m2:
            out.append(
                ConcealedFlag(
                    surface_id=dmg.surface_id,
                    rule_id="R-CONCEAL-MOIST-01",
                    rule_text=RULE_TEXT["R-CONCEAL-MOIST-01"],
                    inputs=inputs,
                    evidence_ref=evidence_ref,
                )
            )
        if dmg.cls == "crack" and length > d.struct_crack_len_m:
            out.append(
                ConcealedFlag(
                    surface_id=dmg.surface_id,
                    rule_id="R-CONCEAL-STRUCT-01",
                    rule_text=RULE_TEXT["R-CONCEAL-STRUCT-01"],
                    inputs=inputs,
                    evidence_ref=evidence_ref,
                )
            )
        if dmg.cls == "mold" and area > d.bio_area_m2:
            out.append(
                ConcealedFlag(
                    surface_id=dmg.surface_id,
                    rule_id="R-CONCEAL-BIO-01",
                    rule_text=RULE_TEXT["R-CONCEAL-BIO-01"],
                    inputs=inputs,
                    evidence_ref=evidence_ref,
                )
            )
    return out
