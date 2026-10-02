# 04 — Part 2 Pipeline Overview

```
Owner:           04
Provides:        (none — stage graph + delegate to 04a–04g)
Consumes:        I1–I9
Must-not-change: I1–I9 (definitions live in their owner docs)
Depends-on:      01, 02, 03, 04a
```

This doc is the map. Every stage below is *owned* by a sub-plan; this file only fixes the **order**,
the **stage I/O** (in CIR terms), and the **failure policy**.

## 1. Stage graph

```
 I1 bundle
   │
   ▼
[S1 INGEST] ──► [S2 RECON] ──► [S3 GEOMETRY] ──► [S4 STITCH+DRIFT]
 (04b)           (04b)           (04c)              (04d)
                                                       │
   ┌───────────────────────────────────────────────────┘
   ▼
[S5 DAMAGE] ──► [S6 CONCEALED] ──► [S7 SCOPE] ──► [S8 MEASURE+CI] ──► [S9 OUTPUT]
 (04e)           (04e)              (04e)            (04f)               (04g)
```

- **S1–S2** are the only **tier-specific** stages. Everything from **S3 onward is shared code**.
- All inter-stage payloads are **CIR objects** (`I2`), never ad-hoc dicts.

## 2. Stage I/O in CIR terms

| Stage | In | Out (CIR fields populated) |
|---|---|---|
| S1 Ingest | `I1` bundle | `session`, `frames[]`, `imu` |
| S2 Recon | `frames[]` | `recon{points, pose_graph, scale, scale_source, quality}` |
| S3 Geometry | `recon` | `rooms[]`, `surfaces[]` |
| S4 Stitch+Drift | `rooms[]`,`surfaces[]` | `stitch{plan_frame, edges[], closure[], ablation}` |
| S5 Damage | frames+`surfaces[]` | `damages[]` |
| S6 Concealed | `damages[]`,`surfaces[]` | `concealed[]` |
| S7 Scope | `damages[]`,`concealed[]` | `scope[]` |
| S8 Measure+CI | all geometry+damage | every `Measurement.ci_*` filled |
| S9 Output | full CIR | `plan.json` (I3), `plan.svg`, `report.html` |

## 3. Failure policy (deterministic + honest)

- Any stage may emit `Measurement` with **wide CI** rather than fail — the contract is "results out", not exceptions.
- Hard failures (unreadable input) exit non-zero with a clear message; no partial `plan.json`.
- Every stage is **idempotent** and **cached** by input hash (`01` §7).

## 4. Gate traceability

| Gate | Produced by | Verified by |
|---|---|---|
| G-OPEN (openings ≤2 cm, ≥85%) | `04c` | `08` |
| G-CEIL (≤1.5 cm; spread ≤1 cm) | `04c` (+`04d` for spread) | `08` |
| G-REP (1 cm / 0.5%/wall) | determinism `01` §7 + `04c` | `08` |
| G-DRIFT (correction + ablation) | `04d` | `08` |
| G-PSTITCH (±8%, no overlap) | `04d` | `08` |
| G-TIERACC (photo ±8%, video ±3%) | `04b`+`04f` | `08` |
| Calibration coverage | `04f` | `08` |

## 5. Sub-plan index

`04a` CIR/schema · `04b` recon · `04c` geometry · `04d` stitch/drift · `04e` damage/scope ·
`04f` uncertainty · `04g` output/CLI. Each declares `Provides`/`Consumes` against `I2`,`I6`,`I8`.