# 00 — Master Implementation Plan

```
Owner:           00 (master)
Provides:        (none — coordination only)
Consumes:        I1–I9 (references them, defines none)
Must-not-change: I1–I9
Depends-on:      —
```

## 1. Objective

Build, from the phone's sensors onward, a pipeline that turns **one capture of a property** into a
**stitched, dimensioned, whole-property floor plan with damage assessment** — from **three input tiers
(photos, video, LiDAR)**, with **calibrated confidence intervals** — and prove it cold on the reviewers'
own device (`30%` walk-in test).

**Product surface:** the stitched multi-room plan a homeowner would recognise from poly.cam / magicplan.

## 2. Case-study part → workstream map

| Case-study part | Workstream | Plan doc | Score |
|---|---|---|---|
| Part 1 Capture | Capture route + protocol + bundle | `03` | 5% + enables 30% |
| Part 2 Contract | Pipeline (CIR → geometry → stitch → damage → uncertainty → output) | `04`, `04a`–`04g` | 15% + enables 30% |
| Part 2 Benchmark | Self-built benchmark + ground truth | `08` | under 15% |
| Part 3 Head-to-head | Incumbent comparison | `05` | 10% |
| Part 4 Fix loop | Declare → ship → before/after | `06` | 25% |
| Part 5 Process | Commit history + defense | `07` | 5% |
| Compliance | Requirement→path→artifact→status | `09` | 10% |
| Enabler | Repo/infra/conventions | `02`,`01` | — |

## 3. Milestones

| M | Name | Exit criterion | Docs |
|---|---|---|---|
| **M0** | Foundation | `scan2plan --help` works on clean machine; `git init` done; CI green | `02`,`07` |
| **M1** | Ingest + recon (LiDAR seed) | Seed captures → poses/depth/points in CIR; depth scale confirmed | `04b` |
| **M2** | CIR + schema frozen | `I2`,`I3` tagged; schema validates seed output | `04a` |
| **M3** | Geometry | Seed rooms → walls/openings/ceiling/area in CIR; single-room plan renders | `04c`,`04g` |
| **M4** | Stitch + drift | Multi-room stitch with loop closure + **on/off ablation** | `04d` |
| **M5** | Damage + scope | Two damage classes detected; concealed rules + scope items | `04e` |
| **M6** | Uncertainty | Calibrated CI per tier; coverage report | `04f` |
| **M7** | Benchmark | BM-1..BM-5 captured; all gates computed per tier | `08` |
| **M8** | Head-to-head + fix loop | ≥70% shared dims; fix shipped before/after | `05`,`06` |
| **M9** | Deliverables | Repro bundle, reports, compliance matrix | `09` |

## 4. Dependency DAG

See `README.md` §6. Critical path: **M1 → M2 → M3 → M4 → M7 → M8 → M9**.

## 5. Scoring alignment (monitor weekly)

| Score | Owned by | Leading indicator |
|---|---|---|
| 30% walk-in | `04b/04c/04d/04g` + `03` | Cold run on unseen capture passes `I3`; opens/ceiling within gate |
| 25% fix loop | `06` | Worst gate identified with evidence; before/after regenerable |
| 15% benchmark | `04f`+`08` | Per-tier error + calibration coverage tables |
| 10% compliance | `09` | Coverage % of requirement matrix |
| 10% head-to-head | `05` | ≥70% dimensions tie-or-beat |
| 5% capture route | `03` | Install <10 min measured; protocol unambiguous |
| 5% process | `07` | Commit history matches build order |

## 6. Global NFRs (apply to every doc)

- **Offline / no own infrastructure** — runs locally; weights fetched by `scripts/fetch_weights.sh`.
- **One command per capture** (`I5`); clean-machine setup < 15 min.
- **Determinism** — seeds fixed; caches keyed by input hash; cached model outputs replay deterministically **and** the live path runs (walk-in).
- **Disclosure** — every pretrained model/dataset/API listed in `09`.
- **Honest intervals** — CI widens as data thins (`04f`); never "confident garbage".
- **Drift never "as-is"** — always a correction method + ablation (`04d`).

## 7. Seed dataset (discovered in repo — authoritative input)

Three **LiDAR-tier** captures already present (format = `I1`):

| Path | Rooms | Frames | Duration | Notes |
|---|---|---|---|---|
| `single_room/c00a170fe1/` | 1 | 1715 | ~29 s | baseline single room |
| `single_scan_floor_only/1a8384c3f6/` | 1 | 5251 | ~88 s | floor emphasised |
| `single_scan_with_ceiling/c7d28f72c6/` | 1 | 9745 | ~162 s | full room incl. ceiling |

Per capture: `rgb.mp4` (HEVC 1920×1440@60), `depth/*.png` (uint16 256×192, ~506–3732 ⇒ **mm**),
`confidence/*.png` (uint8 {0,1,2}), `odometry.csv` (per-frame pose+intrinsics), `camera_matrix.csv` (K), `imu.csv`.

**Gaps to fill (owned by `08`):** no photos tier, no video-only tier, **no multi-room (BM-1)**,
**no staged damage (BM-2)**, **no ground truth (BM-5)**, no repeat-capture (BM-4).

## 8. Top global risks

| Risk | Owner | Mitigation |
|---|---|---|
| Photo-tier metric scale (no depth/poses) | `04b` | disclosed mono-depth + calibrated CI; validated vs G-PSTITCH ±8% |
| Multi-room photo stitch (hardest row) | `04d` | connector matching + pose-graph + plane anchoring |
| Depth units wrong (mm assumption) | `04b` | verify against tape on known wall before M2 |
| Walk-in device has no LiDAR | `03` | device matrix: LiDAR=Pro-only; photos/video always runnable |
| Fix loop unverifiable | `06` | before/after from same code path, input-hash regenerable |
| "Published schema" undefined | `04a` | publish + version our own schema |