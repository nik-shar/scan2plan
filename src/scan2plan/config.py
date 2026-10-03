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


class Outline(BaseModel):
    """Three-stage room-outline thresholds (plan 04i).

    Every threshold that decides a number lives here (never in code) so the stage
    JSONs can record the exact parameters that fired. Defaults are the values
    ported from ``room_fit.py`` (retained) plus the spec's additions.
    """

    model_config = ConfigDict(extra="forbid")

    # Stage 1 - observed cloud gates.
    confidence_min: int = Field(default=1, ge=0, le=2)
    max_range_m: float = Field(default=8.0, gt=0.0)
    # Wall-cell / height support (room_fit wall_cells).
    cell_m: float = Field(default=0.02, gt=0.0)
    height_bins: int = Field(default=10, ge=1)
    min_height_bins: int = Field(default=4, ge=1)
    wall_min_m: float = Field(default=0.25, ge=0.0)
    wall_max_m: float = Field(default=1.9, gt=0.0)
    # Wall-line picking (room_fit _pick_side / _longest_run).
    peak_smooth: int = Field(default=5, ge=1)
    min_peak_frac: float = Field(default=0.15, gt=0.0, le=1.0)
    cam_margin_m: float = Field(default=0.10, ge=0.0)
    min_run_m: float = Field(default=1.2, gt=0.0)
    run_gap_m: float = Field(default=0.10, ge=0.0)
    # Multi-segment wall extraction (stage 2).
    merge_tol_m: float = Field(default=0.25, ge=0.0)
    join_tol_m: float = Field(default=0.30, gt=0.0)
    evidence_tol_m: float = Field(default=0.05, gt=0.0)
    # Wall completion (stage 2): bridge broken lines without erasing openings.
    collinear_tol_m: float = Field(default=0.15, ge=0.0)
    occ_band_m: float = Field(default=0.80, gt=0.0)
    occ_min_cells: int = Field(default=40, ge=1)
    dropout_max_m: float = Field(default=0.30, gt=0.0)
    max_extend_m: float = Field(default=1.00, gt=0.0)
    perp_tol_m: float = Field(default=0.10, gt=0.0)
    ci_base_m: float = Field(default=0.03, ge=0.0)
    ci_per_m: float = Field(default=0.15, ge=0.0)
    # Classification thresholds (stage 2).
    furniture_max_m: float = Field(default=1.0, gt=0.0)
    occluder_inset_m: tuple[float, float] = (0.3, 0.7)
    # Observed-evidence layers (stage 1).
    evidence_bin_m: float = Field(default=0.10, gt=0.0)
    floor_band_m: float = Field(default=0.08, gt=0.0)
    ray_carve: bool = False
    free_stride: int = Field(default=25, ge=1)
    save_unfiltered: bool = True
    # Stage 3 outline regularisation.
    min_step_m: float = Field(default=0.3, gt=0.0)
    max_edges: int = Field(default=8, ge=4)
    snap_deg: float = Field(default=8.0, gt=0.0)
    infer_tol_m: float = Field(default=0.20, gt=0.0)
    inferred_ci_per_m: float = Field(default=0.05, ge=0.0)
    assert_camera_inside: bool = False
    # Intervals.
    odometry_ci_frac: float = Field(default=0.01, ge=0.0)
    weak_coverage_frac: float = Field(default=0.5, gt=0.0, le=1.0)
    occluded_ci_scale: float = Field(default=2.0, ge=1.0)
    bootstrap_n: int = Field(default=200, ge=0)


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
    outline: Outline = Field(default_factory=Outline)


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
