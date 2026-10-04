"""Stage S5-S7 orchestrator: evidence -> damages -> concealed -> scope (plan 04e).

Pure of the CLI: consumes the CIR (surfaces + frames) and writes a
``damage.json`` sidecar recording every threshold, the projection statistics and
the rule text that fired. Never raises on thin evidence (results-out policy) -
it returns empty lists plus a warning so the plan still validates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from scan2plan.cir import CIR, ConcealedFlag, Damage, ScopeItem
from scan2plan.config import Config
from scan2plan.damage.detect import CLASS_ORDER, detect_damages
from scan2plan.damage.evidence import build_surface_evidence
from scan2plan.damage.rules import RULE_TEXT, concealed_flags
from scan2plan.damage.scope import TASK, scope_items
from scan2plan.util.logging import get_logger

logger = get_logger("scan2plan.damage.assess")


@dataclass
class Assessment:
    """The assessment layer produced for one capture (OUT-3/4/5)."""

    damages: list[Damage] = field(default_factory=list)
    concealed: list[ConcealedFlag] = field(default_factory=list)
    scope: list[ScopeItem] = field(default_factory=list)
    report: dict[str, object] = field(default_factory=dict)


def assess(
    cir: CIR,
    capture_dir: Path,
    cfg: Config,
    out_dir: Path,
    *,
    floor_y: float = 0.0,
) -> Assessment:
    """Run S5-S7 for one capture and write ``damage.json``."""
    tmp_dir = out_dir / "cache" / "damage_frames"
    grids, info = build_surface_evidence(cir, capture_dir, cfg, tmp_dir, floor_y=floor_y)
    damages = detect_damages(grids, cfg)
    concealed = concealed_flags(damages, cfg)
    scope = scope_items(damages, cfg, tier=cir.session.tier)

    by_class: dict[str, int] = {}
    for dmg in damages:
        by_class[dmg.cls] = by_class.get(dmg.cls, 0) + 1
    warnings = list(info.get("warnings") or [])
    if not damages and not warnings:
        warnings.append("no damage regions met the thresholds (clean or unmodelled surfaces)")

    report: dict[str, object] = {
        "name": "damage",
        "params": cfg.damage.model_dump(),
        "evidence": info,
        "damage_count": len(damages),
        "by_class": by_class,
        "concealed_count": len(concealed),
        "scope_count": len(scope),
        "taxonomy": list(CLASS_ORDER),
        "scope_map": {k: {"task": v[0], "unit": v[1]} for k, v in TASK.items()},
        "rules": RULE_TEXT,
        "warnings": warnings,
        "calibration": "uncalibrated (plan 04f/08)",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "damage.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return Assessment(damages=damages, concealed=concealed, scope=scope, report=report)
