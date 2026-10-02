"""Schema checks: docs/schema/*.json are valid, and the config conforms (CI step 4)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scan2plan.config import Config

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docs" / "schema"


def _load_schemas() -> list[Path]:
    schemas = sorted(SCHEMA_DIR.glob("*.json"))
    assert schemas, f"no schemas found under {SCHEMA_DIR}"
    return schemas


@pytest.mark.parametrize("schema_path", _load_schemas(), ids=lambda p: p.name)
def test_schema_is_valid_jsonschema(schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)


def test_default_config_validates_against_config_schema() -> None:
    schema = json.loads((SCHEMA_DIR / "config.schema.json").read_text())
    jsonschema.validate(json.loads(Config().model_dump_json()), schema)


def test_config_schema_rejects_unknown_property() -> None:
    schema = json.loads((SCHEMA_DIR / "config.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"definitely_not_a_key": True}, schema)
