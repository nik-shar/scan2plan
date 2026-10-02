"""Config (interface I4) - pydantic v2 model + YAML loader.

Definition mirrors docs/schema/config.schema.json and
docs/plans/01-shared-conventions-and-interfaces.md §8.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CONFIG_FILENAME = "config.yaml"


class Calibration(BaseModel):
    """Calibration settings (owned by plan 04f)."""

    model_config = ConfigDict(extra="forbid")

    model: Literal["conformal", "analytic"] = "conformal"
    nominal: float = Field(default=0.9, gt=0.0, le=1.0)


class Config(BaseModel):
    """Runtime configuration. Unknown keys are rejected (extra=forbid)."""

    model_config = ConfigDict(extra="forbid")

    tier: Literal["auto", "photos", "video", "lidar"] = "auto"
    seed: int = 1337
    depth_scale_m: float = Field(default=0.001, gt=0.0)
    units: Literal["m"] = "m"
    output_dir: str = Field(default="out", min_length=1)
    cache: bool = True
    loop_closure: bool = True
    calibration: Calibration = Field(default_factory=Calibration)


def load_config(path: str | Path | None = None, **overrides: Any) -> Config:
    """Load config from YAML, then apply non-None overrides.

    A missing file yields defaults (a pipeline must run with zero config).
    """
    data: dict[str, Any] = {}
    if path is not None:
        p = Path(path)
        if p.is_file():
            raw = yaml.safe_load(p.read_text()) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"config file {p} must contain a mapping")
            data = raw
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Config.model_validate(data)
