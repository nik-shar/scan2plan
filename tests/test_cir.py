"""Tests for the I2 CIR model and I6 Measurement (plan 04a tasks C-1/C-2)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from scan2plan.cir import CIR, Measurement, Session
from scan2plan.cir.validate import referential_errors


def test_measurement_requires_value_within_interval() -> None:
    with pytest.raises(ValidationError):
        Measurement(
            id="m1",
            kind="wall_length",
            value=3.0,
            unit="m",
            ci_low=2.9,
            ci_high=2.95,  # value outside interval
            method="plane_fit",
            tier="lidar",
        )


def test_measurement_rejects_inverted_interval() -> None:
    with pytest.raises(ValidationError):
        Measurement(
            id="m1",
            kind="k",
            value=3.0,
            unit="m",
            ci_low=3.1,
            ci_high=2.9,  # ci_low > ci_high
            method="plane_fit",
            tier="lidar",
        )


def test_measurement_defaults_nominal_and_half_width() -> None:
    m = Measurement(
        id="m", kind="k", value=1.0, unit="m", ci_low=0.9, ci_high=1.1, method="x", tier="lidar"
    )
    assert m.nominal == 0.9
    assert m.half_width == pytest.approx(0.1)


def test_forbidden_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        Session.model_validate({"id": "x", "tier": "lidar", "unknown": 1})


def test_cir_requires_session_and_provenance() -> None:
    with pytest.raises(ValidationError):
        CIR.model_validate({})


def test_cir_round_trip(valid_plan_dict: dict[str, Any]) -> None:
    cir = CIR.model_validate(valid_plan_dict)
    assert cir.session.id == "cap_c00a170fe1"
    assert len(cir.rooms) == 1
    assert len(cir.openings) == 1  # ADR-0003 field present
    again = json.loads(cir.model_dump_json(exclude_none=True))
    assert CIR.model_validate(again) == cir


def test_referential_integrity_clean(valid_plan_dict: dict[str, Any]) -> None:
    assert referential_errors(CIR.model_validate(valid_plan_dict)) == []


def test_referential_integrity_flags_bad_surface(valid_plan_dict: dict[str, Any]) -> None:
    valid_plan_dict["damages"][0]["surface_id"] = "no_such_surface"
    errors = referential_errors(CIR.model_validate(valid_plan_dict))
    assert errors
    assert any("no_such_surface" in e for e in errors)
