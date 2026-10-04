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


class DamageConfig(BaseModel):
    """Damage-assessment thresholds (plan 04e, OUT-3/4/5).

    Every number that decides a damage region, a concealed flag or a scope
    quantity lives here so ``damage.json`` can record the exact parameters that
    fired. The colour heuristics are **disclosed and uncalibrated** (plan 04e
    section 6); the SAM/CLIP model hook is disclosed in ``docs/plans/09``.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    #: Sample every N-th frame (one ffmpeg pass); bounds runtime on long captures.
    frame_stride: int = Field(default=60, ge=1)
    max_frames: int = Field(default=200, ge=1)
    # Depth/confidence gates (mirror the stage-1 evidence gates).
    confidence_min: int = Field(default=1, ge=0, le=2)
    min_depth_m: float = Field(default=0.30, gt=0.0)
    max_depth_m: float = Field(default=6.00, gt=0.0)
    # Surface projection.
    surface_tol_m: float = Field(default=0.08, gt=0.0)  # |n.p + d| to belong to a wall
    wall_band_m: tuple[float, float] = (0.20, 2.20)  # height band kept on a wall
    cell_m: float = Field(default=0.05, gt=0.0)  # surface evidence grid
    min_cell_count: int = Field(default=3, ge=1)  # samples before a cell is trusted
    min_region_cells: int = Field(default=6, ge=1)
    min_region_area_m2: float = Field(default=0.02, gt=0.0)
    # Colour heuristics (RGB 0-255) - disclosed, uncalibrated.
    mold_max_lum: float = Field(default=95.0, ge=0.0, le=255.0)
    mold_max_sat: float = Field(default=0.40, ge=0.0, le=1.0)
    stain_min_rb: float = Field(default=18.0, ge=0.0)  # R - B (yellow/brown tint)
    stain_max_lum: float = Field(default=205.0, ge=0.0, le=255.0)
    crack_min_grad: float = Field(default=45.0, ge=0.0)
    crack_min_length_m: float = Field(default=0.30, gt=0.0)
    crack_min_aspect: float = Field(default=2.5, ge=1.0)
    peel_min_grad: float = Field(default=30.0, ge=0.0)
    peel_min_area_m2: float = Field(default=0.03, gt=0.0)
    #: Fixed per-region detection confidence until 04f calibrates it.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    #: Relative half-width on a damage extent interval (S8, 04f).
    extent_rel_ci: float = Field(default=0.25, ge=0.0)
    # Concealed-damage rule thresholds (plan 04e section 3).
    moisture_area_m2: float = Field(default=0.30, gt=0.0)
    struct_crack_len_m: float = Field(default=1.00, gt=0.0)
    bio_area_m2: float = Field(default=0.50, gt=0.0)
    opening_proximity_m: float = Field(default=1.00, gt=0.0)


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
    # Opening-width cap (stage 2): a camera-crossed gap outside this range is not a
    # door - narrower than ``open_min_m`` is a dropout, wider than ``open_max_m`` is
    # an ``open_space`` (a walk-through, not an opening).
    open_min_m: float = Field(default=0.50, gt=0.0)
    open_max_m: float = Field(default=2.50, gt=0.0)
    # Evidence split (stage 2): an unexplained-cell bin with at least this many cells
    # (on a ``blob_bin_m`` grid) is a dense blob (furniture/occluder); the rest is
    # residual noise.
    blob_bin_m: float = Field(default=0.10, gt=0.0)
    blob_min_cells: int = Field(default=6, ge=1)
    # Wall graph (stage 2): nodes + edges after completion.
    node_tol_m: float = Field(default=0.05, gt=0.0)
    node_merge_m: float = Field(default=0.10, gt=0.0)
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
    # --- Stage 3: rooms, closed polygons, per-room measurements (plan 04c/04h). ---
    # NOTE: these are UNCALIBRATED constants (to be calibrated by plan 04f / 08); they
    # are recorded in every stage-3 payload so a number can be traced to its threshold.
    closure_max_m: float = Field(default=2.50, gt=0.0)  # longest accepted closure run
    closure_wall_tol_m: float = Field(default=0.05, gt=0.0)  # faint wall cells within this
    closure_bonus_m: float = Field(default=1.00, ge=0.0)  # cost removed per metre supported
    closure_floor_penalty: float = Field(default=1.00, ge=0.0)  # cost added per metre on floor
    waist_min_m: float = Field(default=0.60, gt=0.0)  # narrowest doorway-shaped waist
    waist_max_m: float = Field(default=2.50, gt=0.0)  # widest doorway-shaped waist
    room_grid_m: float = Field(default=0.02, gt=0.0)  # region raster grid (2 cm)
    room_min_area_m2: float = Field(default=0.50, gt=0.0)  # drop tiny regions
    mc_samples: int = Field(default=500, ge=0)  # Monte-Carlo interval draws
    ceiling_min_above_floor_m: float = Field(default=2.00, gt=0.0)  # ignore low planes
    ceiling_bin_m: float = Field(default=0.02, gt=0.0)  # ceiling histogram bin
    ceiling_prior_low_m: float = Field(default=2.40, gt=0.0)  # prior interval (no ceiling)
    ceiling_prior_high_m: float = Field(default=2.70, gt=0.0)  # prior interval (no ceiling)
    # --- Stage-3 invariant gates (plan 04i fix-loop section 1; uncalibrated). ---
    # Every invariant prints its values and fails loudly when violated.
    min_room_area_m2: float = Field(default=2.00, gt=0.0)  # a room is at least this big
    min_room_inradius_m: float = Field(default=0.60, ge=0.0)  # ...and this wide inside
    coverage_min: float = Field(default=0.95, ge=0.0, le=1.0)  # camera cells inside regions
    ceiling_min_cells: int = Field(default=200, ge=1)  # measured ceiling: min near cells
    ceiling_min_footprint_frac: float = Field(
        default=0.20, ge=0.0, le=1.0
    )  # ...covering this share of the room footprint
    ceiling_height_low_m: float = Field(default=2.10, gt=0.0)  # plausible measured band
    ceiling_height_high_m: float = Field(default=4.00, gt=0.0)  # plausible measured band
    ceiling_spread_max_m: float = Field(default=0.30, ge=0.0)  # across-room spread flag
    ceiling_global_tol_m: float = Field(
        default=0.30, ge=0.0
    )  # per-room peak vs the stage-1 global ceiling
    overlap_tol_m2: float = Field(default=0.0001, ge=0.0)  # total pairwise room overlap (1 cm^2)


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
    damage: DamageConfig = Field(default_factory=DamageConfig)


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
