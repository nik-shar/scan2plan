# 08 — Benchmark Set & Ground Truth

```
Owner:           08
Provides:        I9 (benchmark manifest + ground-truth schema)
Consumes:        I1 (bundles), I5 (run), I3 (plan), I6
Must-not-change: I1–I8
Depends-on:      01, 02, 03
```

The brief fixes the benchmark composition so it **"cannot be flattered"**. We build it and commit it.

## 1. Required composition (BM-1..BM-5)

| ID | Requirement | Status from seeds |
|---|---|---|
| BM-1 | One multi-room capture: **3+ rooms + connector** | **MISSING** — must capture |
| BM-2 | One furnished room, **staged damage, 2 classes** | **MISSING** — must stage |
| BM-3 | Same rooms at **all 3 tiers** (incl. multi-room); photo tier as per-room folders that **must stitch** | **partial** — LiDAR seeds exist |
| BM-4 | ≥1 room captured **twice at same tier** | **MISSING** |
| BM-5 | **Laser/tape ground truth** on everything; raw data + measurements submitted | **MISSING** |

## 2. Existing seed captures (LiDAR tier)

| Group | id | frames | dur | use |
|---|---|---|---|---|
| `single_room/` | `c00a170fe1` | 1715 | ~29 s | single-room baseline |
| `single_scan_floor_only/` | `1a8384c3f6` | 5251 | ~88 s | floor emphasis |
| `single_scan_with_ceiling/` | `c7d28f72c6` | 9745 | ~162 s | full room + ceiling |

## 3. capture plan (to build)

1. **R1 multi-room:** living + kitchen + hallway + bathroom **+ connector** (corridor/door).
2. **R2 furnished staged:** one room with **two staged classes** (e.g. `water_stain` + `crack`).
3. **Re-capture R1, R2** to satisfy BM-3 (photos folders, video) and BM-4 (one room twice).
4. **Ground truth:** laser/tape for wall lengths, opening widths, ceiling heights, room areas → `bench/ground_truth/<room>.json`.

## 4. Ground-truth schema (I9)

```json
{"room_id":"room_living","method":"laser",
 "walls":[{"id":"room_living_wall_1","length_m":4.123}],
 "openings":[{"id":"open_room_living_1","kind":"door","width_m":0.812,"height_m":2.031}],
 "ceiling_height_m":2.441,"floor_area_m2":12.06}
```

## 5. Harness (`bench/runner.py`)

For each tier: ingest→run→ compare to ground truth → compute:
- opening width error + **detection P/R** (misses & phantoms), pass-rate vs 85%;
- ceiling height error + **across-capture spread**;
- **repeatability** (1 cm / 0.5%/wall);
- footprint error (±8% photo);
- **drift ablation delta**;
- **calibration coverage**.
Emit tables consumed by the benchmark report (`09`) and the fix loop (`06`).

## 6. Tasks

| ID | Task | Done when |
|---|---|---|
| BM-1..BM-4 | Capture sets per §3 | bundles conform to `I1` |
| BM-5 | Ground truth measured | `I9` files complete |
| BMt | Benchmark manifest | lists each capture×tier×gt |
| BMx | Harness computes all gates | tables generated |

## 7. Risks

| Risk | Mitigation |
|---|---|
| Multi-room stitch harder than expected | capture connector explicitly in protocol |
| Photo-tier folders insufficient | protocol: outward shots at folder boundary |
| GT inconsistent with sensor frames | measure per room with tape backup |
| Staged damage unrealistic | use natural materials; 2 clearly distinct classes |