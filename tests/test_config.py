"""Tests for the I4 config model and YAML loader (plan 02, task F-3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scan2plan.config import Calibration, Config, load_config


def test_defaults() -> None:
    cfg = Config()
    assert cfg.tier == "auto"
    assert cfg.seed == 1337
    assert cfg.depth_scale_m == 0.001
    assert cfg.units == "m"
    assert cfg.output_dir == "out"
    assert cfg.cache is True
    assert cfg.loop_closure is True
    assert cfg.calibration == Calibration(model="conformal", nominal=0.9)


def test_load_config_missing_file_yields_defaults() -> None:
    assert load_config("does/not/exist.yaml") == Config()


def test_load_config_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("tier: lidar\nseed: 7\ncache: false\nloop_closure: false\n")
    cfg = load_config(path)
    assert cfg.tier == "lidar"
    assert cfg.seed == 7
    assert cfg.cache is False
    assert cfg.loop_closure is False


def test_overrides_applied_but_none_ignored() -> None:
    cfg = load_config(None, tier="video", seed=None, output_dir="elsewhere")
    assert cfg.tier == "video"
    assert cfg.seed == 1337  # None override must not clobber the default
    assert cfg.output_dir == "elsewhere"


def test_unknown_key_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"nope": 1})


def test_invalid_tier_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"tier": "radar"})


def test_nonpositive_depth_scale_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"depth_scale_m": 0.0})


def test_calibration_nominal_bounds() -> None:
    with pytest.raises(ValidationError):
        Calibration(nominal=1.5)


def test_config_file_must_be_mapping(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="must contain a mapping"):
        load_config(path)
