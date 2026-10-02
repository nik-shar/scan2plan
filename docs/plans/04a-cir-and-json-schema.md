# 04a — CIR Data Model & Published JSON Schema (frozen contract)

```
Owner:           04a
Provides:        I2 (CIR), I3 (output schema)
Consumes:        I7 (frames/units), I6 (measurement type from 04f)
Must-not-change: I1, I4, I5
Depends-on:      01, 02
```

This is the **contract everything targets** (chosen area). `I2`/`I3` are **FROZEN at M2** and tagged.

## 1. CIR top-level (I2)

```python
class CIR(BaseModel):
    schema_version: str                      # "1.0"
    session: Session
    frames: list[Frame] = []
    recon: Recon | None = None
    rooms: list[Room] = []
    surfaces: list[Surface] = []
    stitch: Stitch | None = None
    damages: list[Damage] = []
    concealed: list[ConcealedFlag] = []
    scope: list[ScopeItem] = []
    measures: list[Measurement] = []         # I6
    provenance: Provenance
```

### 1.1 Session
`id, tier∈{photos,video,lidar}, device, ios, tool{name,version}, captured_at, rooms_expected:int`

### 1.2 Frame
`idx:int, t:float, rgb_ref:str, depth_ref:str|None, conf_ref:str|None, pose:T_wc|None, K:Mat3|None`

### 1.3 Recon
`points_ref, scale:float, scale_source∈{lidar,mono_depth,vio,reference}, pose_graph_ref,
 quality{track_len, mean_reproj, plane_rms, coverage}`

### 1.4 Room / Surface / Opening
- `Room{id, name, boundary:Polygon2D, ceiling_height:Measurement, floor_area:Measurement}`
- `Surface{id, room_id, type∈{wall,ceiling,floor}, plane{normal,d}, polygon:Polygon2D}`
- `Opening{id, room_id, surface_id, kind∈{door,window,passage}, width:Measurement, height:Measurement}`

### 1.5 Stitch
`plan_frame, room_transforms{room_id→SE2}, edges[], closures[], overlap_ok:bool,
 ablation{loop_closure_on:Footprint, off:Footprint}`

### 1.6 Damage / Concealed / Scope
- `Damage{id, surface_id, cls, polygon:Polygon2D, extent{area_m2,bbox_m}, evidence_ref, confidence}`
- `ConcealedFlag{surface_id, rule_id, rule_text, inputs{}, evidence_ref}`
- `ScopeItem{id, surface_id, task, quantity:Measurement}`

## 2. Output schema (I3) = serialization rules

`docs/schema/plan.schema.json` (JSON Schema **2020-12**). Mapping rules:

1. `Measurement` → `{value, unit, ci_low, ci_high, method, tier}` (**required** everywhere).
2. Geometry emitted in **both** `world` (stitched) and per-`room` frames.
3. Every `Damage`/`ConcealedFlag` references an existing `surface_id` (referential integrity).
4. `unstitched:false` required for multi-room captures; `overlap_ok:true` required by G-PSTITCH.
5. `provenance` block required: tier, tool+version, model list, git sha, seed.

## 3. Example (abridged)

```json
{
  "schema_version": "1.0",
  "session": {"id":"cap_c00a170fe1","tier":"lidar","device":"iPhone 16 Pro",
              "tool":{"name":"<logger>","version":"x.y"}},
  "rooms":[{"id":"room_living","ceiling_height":{"value":2.44,"unit":"m","ci_low":2.43,
            "ci_high":2.45,"method":"plane_fit","tier":"lidar"}}],
  "surfaces":[{"id":"room_living_wall_1","room_id":"room_living","type":"wall"}],
  "stitch":{"plan_frame":"stitched_world_xy","overlap_ok":true,
            "ablation":{"loop_closure_on":{"footprint_m2":42.1},"off":{"footprint_m2":40.7}}},
  "damages":[{"id":"dmg_9f31ab07","surface_id":"room_living_wall_1","cls":"water_stain",
              "extent":{"area_m2":0.42}}]
}
```

## 4. Freeze process (M2)

1. `I2` pydantic models committed under `src/scan2plan/cir/model.py`.
2. `I3` schema generated/validated against `CIR.model_json_schema()`.
3. `scan2plan validate plan.json` passes on a seed-derived `plan.json`.
4. **Tag `iface-v1.0`**; downstream plans may only *consume*.

## 5. Tasks

| ID | Task | Done when |
|---|---|---|
| C-1 | Implement `cir/model.py` (pydantic v2) | mypy strict passes |
| C-2 | `cir/measure.py` import hooks for I6 | Measurement used everywhere |
| C-3 | Author `plan.schema.json` | valid 2020-12, `jsonschema` validates example |
| C-4 | `scan2plan validate` | CI checks every produced plan |
| C-5 | Freeze + tag | `iface-v1.0` created |

## 6. Risks

| Risk | Mitigation |
|---|---|
| Schema churn breaks downstream | append-only (R4); ADR for breaking changes |
| Measurement omitted somewhere | mypy + grep gate in CI for bare floats |
| Frame ambiguity | `01` §4 defines frames; schema embeds frame name |