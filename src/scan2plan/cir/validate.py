"""Validate a ``plan.json`` against interface I3 (schema + referential integrity).

I3 mapping rules (plan 04a §2): JSON-Schema shape, plus rule 3 — every
``Damage``/``ConcealedFlag``/``ScopeItem``/``Opening`` must reference an existing
``surface_id`` (and surfaces/openings must reference an existing ``room_id``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import ValidationError

from scan2plan.cir.model import CIR

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "docs" / "schema" / "plan.schema.json"


def referential_errors(cir: CIR) -> list[str]:
    """Return referential-integrity violations (empty if consistent)."""
    errors: list[str] = []
    room_ids = {r.id for r in cir.rooms}
    surface_ids = {s.id for s in cir.surfaces}

    for s in cir.surfaces:
        if s.room_id not in room_ids:
            errors.append(f"surface '{s.id}' references unknown room '{s.room_id}'")
    for o in cir.openings:
        if o.room_id not in room_ids:
            errors.append(f"opening '{o.id}' references unknown room '{o.room_id}'")
        if o.surface_id not in surface_ids:
            errors.append(f"opening '{o.id}' references unknown surface '{o.surface_id}'")
    for d in cir.damages:
        if d.surface_id not in surface_ids:
            errors.append(f"damage '{d.id}' references unknown surface '{d.surface_id}'")
    for c in cir.concealed:
        if c.surface_id not in surface_ids:
            errors.append(f"concealed flag references unknown surface '{c.surface_id}'")
    for item in cir.scope:
        if item.surface_id not in surface_ids:
            errors.append(f"scope item '{item.id}' references unknown surface '{item.surface_id}'")
    return errors


def validate_plan(data: dict[str, Any], *, schema_path: Path | None = None) -> list[str]:
    """Validate a plan dict; return a list of error messages (empty = valid).

    1. JSON-Schema (I3) validation.
    2. CIR model parse (belt-and-braces; the schema is derived from the model).
    3. Referential-integrity checks (I3 rule 3).
    """
    path = schema_path or DEFAULT_SCHEMA_PATH
    schema = json.loads(path.read_text())

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(e.message for e in validator.iter_errors(data))
    if errors:
        return errors

    try:
        cir = CIR.model_validate(data)
    except ValidationError as exc:
        return [f"CIR model: {exc}"]
    return referential_errors(cir)
