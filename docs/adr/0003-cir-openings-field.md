# ADR-0003 — CIR carries a top-level `openings` list

* Status: Accepted
* Date: 2026-10
* Owner plan: `docs/plans/04a-cir-and-json-schema.md` (interface I2)
* Supersedes: —

## Context

Plan `04a` §1.4 defines the `Opening` model (door/window/passage with width/height),
and OUT-1 / G-OPEN require openings in the emitted plan. However the plan's §1 CIR
listing defines `frames/rooms/surfaces/...` but **never includes an `openings`
list** — an interface gap that would leave OUT-1 openings with no home.

## Decision

Add an **optional, defaulted** top-level field to the CIR:

```python
openings: list[Opening] = []
```

## Consequences

* Append-only (rule R4): the field is optional with an empty default, so existing
  producers/consumers are unaffected and `I2`/`I3` need no breaking change.
* Openings are emitted with room/surface references (referential integrity is
  checked by `scan2plan.cir.validate`, I3 rule 3).
* The published `plan.schema.json` is regenerated from `CIR.model_json_schema()` and
  therefore includes `openings`.

## Alternatives considered

* Nest openings inside each `Surface` — rejected: OUT-1 wants openings as first-class,
  measurable entities keyed to a room, and stitching matches openings across rooms.