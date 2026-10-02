"""Build the I3 provenance block (plan 04a section 2, rule 5).

Every produced ``plan.json`` must carry tier, tool+version, model list, git sha and
seed so a number can be traced and reproduced.
"""

from __future__ import annotations

import subprocess
from typing import Any

from scan2plan import __version__
from scan2plan.cir import ModelRef, Provenance, Tool
from scan2plan.cir.measure import Tier
from scan2plan.config import Config


def current_git_sha() -> str | None:
    """Return the current git commit sha, or None outside a repo / without git."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    sha = out.stdout.strip()
    return sha or None


def build_provenance(tier: Tier, config: Config, meta: dict[str, Any] | None = None) -> Provenance:
    """Assemble a ``Provenance`` from tier + config + optional bundle ``meta.json``."""
    meta = meta or {}
    tool = None
    raw_tool = meta.get("tool")
    if isinstance(raw_tool, dict):
        tool = Tool(
            name=str(raw_tool.get("name", "unknown")), version=str(raw_tool.get("version", ""))
        )

    models = [
        ModelRef(
            name=str(m.get("name", "unknown")),
            version=str(m.get("version", "")),
            licence=m.get("licence"),
            where=m.get("where"),
        )
        for m in meta.get("models", [])
        if isinstance(m, dict)
    ]

    device = meta.get("device")
    return Provenance(
        tier=tier,
        tool=tool,
        device=str(device) if device is not None else None,
        git_sha=current_git_sha(),
        code_version=__version__,
        seed=config.seed,
        models=models,
    )
