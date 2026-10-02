"""Tests for interface I3 (plan.schema.json) — plan 04a tasks C-3/C-4."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from scan2plan.cir.schema import PLAN_SCHEMA_ID, build_plan_schema
from scan2plan.cir.validate import validate_plan

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "schema" / "plan.schema.json"


def test_schema_is_valid_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(json.loads(SCHEMA_PATH.read_text()))


def test_committed_schema_matches_model() -> None:
    """The published schema is derived from the CIR model and must not drift (rule R3)."""
    committed = json.loads(SCHEMA_PATH.read_text())
    assert committed == build_plan_schema()


def test_schema_identity() -> None:
    committed = json.loads(SCHEMA_PATH.read_text())
    assert committed["$id"] == PLAN_SCHEMA_ID
    assert committed["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_valid_plan_passes(valid_plan_dict: dict[str, Any]) -> None:
    assert validate_plan(valid_plan_dict, schema_path=SCHEMA_PATH) == []


def test_plan_missing_required_field_fails(valid_plan_dict: dict[str, Any]) -> None:
    del valid_plan_dict["provenance"]
    assert validate_plan(valid_plan_dict, schema_path=SCHEMA_PATH)


def test_plan_unknown_key_fails(valid_plan_dict: dict[str, Any]) -> None:
    valid_plan_dict["bogus"] = 1
    assert validate_plan(valid_plan_dict, schema_path=SCHEMA_PATH)


def test_plan_referential_integrity_fails(valid_plan_dict: dict[str, Any]) -> None:
    valid_plan_dict["damages"][0]["surface_id"] = "ghost_surface"
    errors = validate_plan(valid_plan_dict, schema_path=SCHEMA_PATH)
    assert errors
    assert any("ghost_surface" in e for e in errors)


def test_plan_bad_tier_fails(valid_plan_dict: dict[str, Any]) -> None:
    valid_plan_dict["session"]["tier"] = "radar"
    assert validate_plan(valid_plan_dict, schema_path=SCHEMA_PATH)


def test_plan_bad_damage_class_fails(valid_plan_dict: dict[str, Any]) -> None:
    valid_plan_dict["damages"][0]["cls"] = "rust"  # not in the closed taxonomy
    assert validate_plan(valid_plan_dict, schema_path=SCHEMA_PATH)
