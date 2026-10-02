"""Interface I3: the published ``plan.schema.json`` derived from the CIR model.

Plan 04a §2 requires I3 to be generated/validated from ``CIR.model_json_schema()``
so it cannot drift from I2 (risk: schema churn). The committed
``docs/schema/plan.schema.json`` is regenerated here; a test asserts equality.
"""

from __future__ import annotations

import json
from typing import Any

from scan2plan.cir.model import CIR

SCHEMA_URL = "https://json-schema.org/draft/2020-12/schema"
PLAN_SCHEMA_ID = "https://scan2plan.local/schema/plan.schema.json"
PLAN_SCHEMA_TITLE = "scan2plan plan (interface I3)"
PLAN_SCHEMA_DESCRIPTION = (
    "Published output schema produced by `scan2plan run` (see docs/plans/04a section 2). "
    "Derived from `scan2plan.cir.model.CIR` so it cannot drift from interface I2. "
    "Referential integrity (rule 3) is enforced separately by `scan2plan.cir.validate`."
)


def build_plan_schema() -> dict[str, Any]:
    """Return the published I3 schema as a 2020-12 JSON Schema dict."""
    schema = CIR.model_json_schema(mode="serialization")
    header = {
        "$schema": SCHEMA_URL,
        "$id": PLAN_SCHEMA_ID,
        "title": PLAN_SCHEMA_TITLE,
        "description": PLAN_SCHEMA_DESCRIPTION,
    }
    # Keep CIR's generated body but let the header own title/description.
    return {**header, **{k: v for k, v in schema.items() if k not in ("title", "description")}}


def dumps_plan_schema() -> str:
    """Serialise the I3 schema deterministically (2-space indent, trailing newline)."""
    return json.dumps(build_plan_schema(), indent=2) + "\n"
