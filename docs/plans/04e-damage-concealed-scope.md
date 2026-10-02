# 04e — Damage, Concealed Flags & Scope Line Items

```
Owner:           04e
Provides:        damages[], concealed[], scope[] in I2
Consumes:        frames + surfaces[] (04c), I6, I2
Must-not-change: I1, I2, I3, I8, I6
Depends-on:      04a, 04c
```

Fills the assessment layer of the contract (OUT-3, OUT-4, OUT-5).

## 1. Damage detection (OUT-3)

1. **Region proposal:** promptable segmentation (SAM-family) over frames; project masks onto surfaces via `I8` poses.
2. **Classification:** closed set (declare + version), e.g. `{crack, water_stain, mold, spalling,
   paint_peel, rot}`. Zero-shot CLIP or fine-tuned head; **disclosed**.
3. **Surface keying:** each damage references an existing `surface_id` (referential integrity in `I3`).
4. **Metric extent:** polygon projected to surface plane → `extent{area_m2, bbox_m}` (in metres).

**Benchmark requirement (BM-2):** one furnished room with **two staged damage classes** → validates the
taxonomy end-to-end.

## 2. Damage taxonomy (we define it; the brief does not)

| Class | Signal | Metric extent |
|---|---|---|
| crack | line-like, high contrast | length + width |
| water_stain | diffuse colour shift | area |
| mold | dark cluster, texture | area |
| spalling | surface loss, depth step | area |
| paint_peel | edge fragmentation | area |
| rot | wood discolour | area |

## 3. Concealed-damage rules (OUT-4) — versioned rule engine

Each rule has an **id**, text, inputs, and evidence; **the id that fired** is emitted.

| rule_id | Fires when | Emits |
|---|---|---|
| R-CONCEAL-MOIST-01 | water_stain/mold near plumbing or opening, area > T | concealed moisture |
| R-CONCEAL-STRUCT-01 | crack length > T near opening/load path | concealed structural |
| R-CONCEAL-BIO-01 | mold cluster area > T, low light/vent | concealed biological |

Rule outputs are `ConcealedFlag{surface_id, rule_id, rule_text, inputs, evidence_ref}`.

## 4. Scope line items (OUT-5)

Map `surface_id` + damage → repair task with **quantity/unit**:

| Damage | Task | Quantity |
|---|---|---|
| crack | seal/patch crack | length (m) |
| water_stain | treat + repaint | area (m²) |
| mold | remediate | area (m²) |
| spalling | re-plaster | area (m²) |

`ScopeItem{id, surface_id, task, quantity:Measurement}` — keyed to surfaces, quantities are `Measurement`.

## 5. Tasks

| ID | Task | Done when |
|---|---|---|
| D-1 | Segmenter wired (disclosed model) | masks on staged room |
| D-2 | Classifier (closed taxonomy) | 2 staged classes separated |
| D-3 | Surface projection + metric extent | area/bbox in metres |
| D-4 | Rule engine + ids | flag carries `rule_id` |
| D-5 | Scope mapper | items keyed to surfaces |

## 6. Risks

| Risk | Mitigation |
|---|---|
| Class bleed between similar classes | confidence threshold; report confusion matrix |
| Projection error on oblique views | multi-view voting; require ≥2 views |
| Rule thresholds arbitrary | expose as config; validate on staged room |
| Disclosure missing | every model in `09` |