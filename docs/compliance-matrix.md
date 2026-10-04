# Compliance matrix — requirement → file path → artifact → status

**Submission scope: LiDAR tier only.** The photos and video recon front-ends (plan
`04b`, tasks B-2/B-3) are **not implemented**; every row that depends on them is
marked ⬜ and declared, not hidden. The LiDAR tier runs end to end from the phone's
sensors to a schema-valid, rendered plan with damage assessment.

Status legend: ✅ delivered · 🟡 partial (present but limited/unmeasured) · ⬜ not delivered.

## 1. Part 1 — Capture route

| ID | Requirement | File path | Artifact | Status |
|---|---|---|---|---|
| CAP-1 | One of the two capture routes, shipped | `docs/adr/0001-capture-route.md`, `docs/protocol.md` | ADR + one-page protocol (Route 2, stock tools) | ✅ |
| CAP-2 | Non-engineer protocol: install, walk, duration, avoid, hand-off | `docs/protocol.md` | protocol page | ✅ |
| CAP-3.1 | Photos tier (2–8 stills/room) | — | — | ⬜ (dropped; LiDAR-only) |
| CAP-3.2 | Video tier (handheld clip) | — | — | ⬜ (dropped; LiDAR-only) |
| CAP-3.3 | LiDAR tier (depth + poses + K) | `src/scan2plan/ingest/`, `src/scan2plan/recon/lidar.py` | CIR frames + recon | ✅ |
| CAP-4 | Device matrix (tier × hardware + honest accuracy) | `docs/device-matrix.md` | device matrix | ✅ |
| CAP-5 | Bundle builder normalises a raw logger export to I1 | `src/scan2plan/ingest/build.py`, `scripts/build_bundle.sh` | `bundles/<id>/` | ✅ |
| CAP-6 | Capture QA before leaving the room | `scripts/check_bundle.py` | coverage/travel report | ✅ |
| CAP-7 | One command per capture | `scripts/run_capture.sh` | run log | ✅ |

## 2. Part 2 — Output contract

| ID | Requirement | File path | Artifact | Status |
|---|---|---|---|---|
| OUT-1 | Dimensioned per-room plan: walls, ceiling, floor area, openings | `src/scan2plan/geometry/rooms.py`, `walls.py`, `wall_complete.py`, `wall_graph.py` | `stage3_rooms.json`, `plan.json` | ✅ |
| OUT-2 | Stitched multi-room plan, correct adjacency, no overlap | `src/scan2plan/stitch/`, `stitch/wire.py` | `stitch{}` in `plan.json`, `plan.svg` | 🟡 (stitch runs; multi-room GT not measured) |
| OUT-3 | Per-surface damage regions, class + metric extent | `src/scan2plan/damage/detect.py`, `evidence.py` | `damages[]`, `damage.json` | 🟡 (disclosed heuristic; not calibrated) |
| OUT-4 | Concealed-damage flags with the rule that fired | `src/scan2plan/damage/rules.py` | `concealed[]` (carries `rule_id`) | ✅ |
| OUT-5 | Scope line items keyed to surfaces | `src/scan2plan/damage/scope.py` | `scope[]` | ✅ |
| OUT-6 | A confidence interval on every measurement | `src/scan2plan/cir/measure.py`, `geometry/rooms.py` | `Measurement.ci_*` | 🟡 (intervals present; uncalibrated, see G-CAL) |
| OUT-7 | One command per capture | `src/scan2plan/cli.py` (`run`) | `out/<id>/` | ✅ |
| OUT-8 | JSON to the published schema | `docs/schema/plan.schema.json`, `src/scan2plan/cir/validate.py` | `plan.json` + `validate` | ✅ |
| OUT-9 | Rendered plan | `src/scan2plan/render/plan_svg.py`, `svg.py` | `plan.svg`, `ablation.svg` | ✅ |

## 3. Part 2 — Gates (Round 1 + the five additions)

| Gate | Target | Verified by | Status |
|---|---|---|---|
| G-OPEN | openings ≤ 2 cm on ≥ 85 %; detection scored | needs BM-5 GT | ⬜ (not measured) |
| G-CEIL | ceiling ≤ 1.5 cm/room; spread ≤ 1 cm | needs BM-4/BM-5 | ⬜ (not measured) |
| G-REP | two captures agree within 1 cm or 0.5 %/wall | needs BM-4 | ⬜ (not measured) |
| G-DRIFT | stated correction + on/off ablation | `stitch/core.py` `run_ablation`, `stitch/wire.py`, `ablation.svg` | 🟡 (method + figure shipped; ablation degenerate on single-frame seeds) |
| G-PSTITCH | photo folders → one stitched plan, no overlap | `stitch/` | ⬜ (photo tier dropped) |
| G-TIERACC | photo ±8 %, video ±3 % | `recon/` | ⬜ (photo/video dropped) |
| G-CAL | calibration coverage at every tier | `04f` (not implemented) | ⬜ |

## 4. Part 2 — Benchmark set (self-built, composition fixed by the brief)

| ID | Requirement | File path | Artifact | Status |
|---|---|---|---|---|
| BM-1 | One multi-room capture, 3+ rooms + connector | `single_scan_floor_only/1a8384c3f6/` (multi-room seed) | capture bundle | 🟡 (multi-room seed present; no laser GT) |
| BM-2 | One furnished room, staged damage, 2 classes | — | — | ⬜ (not captured) |
| BM-3 | Same rooms at all 3 tiers (photo folders must stitch) | — | — | ⬜ (LiDAR-only) |
| BM-4 | ≥1 room captured twice at the same tier | — | — | ⬜ (not captured) |
| BM-5 | Laser/tape ground truth on everything | `bench/ground_truth/` (empty) | GT JSON (I9) | ⬜ (not measured) |
| BMt | Benchmark manifest | `docs/schema/benchmark.schema.json` (I9, absent) | manifest | ⬜ |
| BMx | Harness computes all gates | `scan2plan bench` (stub), `bench/runner.py` (absent) | gate tables | ⬜ |

## 5. Parts 3–5

| ID | Requirement | File path | Artifact | Status |
|---|---|---|---|---|
| H-1..H-4 | Head-to-head vs a consumer app, ≥70 % dims, export submitted | `docs/head-to-head.md` (absent) | table + export | ⬜ (needs app + GT) |
| X-1..X-5 | Fix loop: declaration, root cause, shipped fix, regenerable before/after | `docs/fix-declaration.md` (absent); `CHANGELOG.md`; `bench/stage2_before|after/`; `out/before_ceiling_fix/` | before/after runs | 🟡 (fixes + evidence exist; not packaged as the required bundle) |
| PR-1..PR-5 | Process: commit-per-task history, CHANGELOG, tags, defense kit | git history; `CHANGELOG.md`; `docs/defense.md` (absent) | history + CHANGELOG | 🟡 (history + CHANGELOG ✅; `defense.md` absent) |

## 6. Deliverables

| # | Deliverable | File path | Status |
|---|---|---|---|
| 1 | Compliance matrix | `docs/compliance-matrix.md` | ✅ (this file) |
| 2 | Capture route + device matrix | `docs/protocol.md`, `docs/device-matrix.md` | ✅ |
| 3 | Repo + README, one command/capture, <15 min setup | `README.md`, `scripts/bootstrap.sh`, `scripts/run_capture.sh` | ✅ |
| 4 | Reproduction bundle | `repro/README.md`, `scripts/reproduce.sh` | ✅ (regenerates pipeline + B-0 numbers) |
| 5 | Benchmark report | `docs/benchmark-report.md` (absent) | ⬜ (blocked on BM-5 GT) |
| 6 | Fix-loop bundle | `messages/fix_loop/` (absent) | ⬜ (evidence exists; not packaged) |
| 7 | Technical report ≤ 6 pp | `docs/technical-report.md` | ✅ |
| 8 | Raw benchmark data + ground truth | seed bundles (git-ignored binaries) + `bench/ground_truth/` (empty) | 🟡 (raw seeds present; GT missing) |

## 7. Frozen interfaces (I1–I9)

| ID | Interface | File path | Status |
|---|---|---|---|
| I1 | Raw capture bundle | `docs/plans/01` §6; `src/scan2plan/ingest/bundle.py` | ✅ |
| I2 | CIR | `src/scan2plan/cir/model.py` | ✅ |
| I3 | Published output schema | `docs/schema/plan.schema.json` | ✅ |
| I4 | Config schema | `docs/schema/config.schema.json`, `src/scan2plan/config.py` | ✅ |
| I5 | CLI contract | `src/scan2plan/cli.py` | ✅ |
| I6 | Measurement + uncertainty | `src/scan2plan/cir/measure.py` | ✅ |
| I7 | Frames + units | `src/scan2plan/util/frames.py`, `docs/adr/0002` | ✅ |
| I8 | Recon artifact (per tier) | `src/scan2plan/recon/` | 🟡 (LiDAR only) |
| I9 | Benchmark manifest + GT schema | `docs/schema/benchmark.schema.json` (absent) | ⬜ |

## 8. Disclosure list (pretrained models / datasets / APIs)

| Model / API / dataset | Version | Licence | Where used | Fetch |
|---|---|---|---|---|
| _(none)_ | — | — | No pretrained model, dataset or API is used anywhere in the pipeline. Recon is geometric (depth + odometry); rooms/walls/stitch are deterministic geometry; the damage region proposer is a **disclosed colour heuristic**, not a model. | — |
| System `ffmpeg` | host | GPL/LGPL (host tool) | RGB frame decode for damage evidence (`damage/frames.py`) | system package |

No weights are fetched and nothing calls external infrastructure (constraint satisfied).

## 9. Coverage summary (honest)

- **LiDAR tier, end to end:** ✅ capture → recon → rooms → stitch + ablation → damage/concealed/scope → schema-valid `plan.json` + `plan.svg` + `ablation.svg`, one command per capture.
- **Delivered now:** 5 of 8 deliverables (1, 2, 3, 4, 7).
- **Not delivered:** the two non-LiDAR tiers and everything that depends on them
  (G-PSTITCH, G-TIERACC, BM-3); the measurement-dependent gates (G-OPEN, G-CEIL,
  G-REP, G-CAL, and the benchmark report + fix-loop bundle) are blocked on **laser
  ground truth (BM-5)** that must be taken physically; the head-to-head (Part 3)
  needs a consumer-app capture.
- **Partial:** OUT-2/OUT-3/OUT-6 and G-DRIFT are implemented but **not yet validated
  against ground truth**; the fix loop has real fixes and evidence in `CHANGELOG.md`
  but is not packaged as the required regenerable bundle.

