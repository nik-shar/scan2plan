# Implementation Plans — Index & Interlock Rules

**Status:** DRAFT v0.1 · Aug 2026
**Scope:** Applied AI Engineer Case Study — phone capture → stitched whole-property plan + damage assessment.

This directory holds one **master plan** plus **per-part / per-module plans**. Their single purpose is to be
**mutually consistent**: each plan declares the interfaces it *owns* and the interfaces it *consumes*, so two
plans can never silently disagree about the same contract.

---

## 1. Document set

| Doc | Title | Case-study part |
|---|---|---|
| `README.md` | This index + interlock rules | — |
| `00-master-implementation-plan.md` | High-level plan across all parts | All |
| `01-shared-conventions-and-interfaces.md` | **Frozen interfaces, units, frames, caching** | All (spine) |
| `02-foundation-repo-and-infra.md` | Repo scaffold, deps, CLI skeleton, CI | Enabler |
| `03-part1-capture.md` | Capture route, protocol, device matrix, bundle writer | Part 1 |
| `04-part2-pipeline-overview.md` | Stage graph + mapping to sub-plans | Part 2 |
| `04a-cir-and-json-schema.md` | CIR model + published JSON schema | Part 2 (OUT-8) |
| `04b-reconstruction-frontends.md` | Photos/video/LiDAR recon + scale | Part 2 |
| `04c-geometry-rooms-openings.md` | Planes, rooms, walls, openings | Part 2 (OUT-1/2) |
| `04d-stitching-and-drift.md` | Pose graph, loop closure, ablation | Part 2 (G-DRIFT) |
| `04e-damage-concealed-scope.md` | Damage, concealed rules, scope items | Part 2 (OUT-3/4/5) |
| `04f-uncertainty-and-calibration.md` | Per-measurement CI, conformal calibration | Part 2 (OUT-6/G-CAL) |
| `04g-output-render-cli.md` | CLI, JSON emit, SVG render | Part 2 (OUT-7/9) |
| `04h-polygonal-room-footprint.md` | L-shaped rooms: concave footprint plan (refines `04c`, no interface change) | Part 2 (OUT-1) |
| `05-part3-head-to-head.md` | Incumbent app comparison | Part 3 |
| `06-part4-fix-loop.md` | Fix declaration → shipped fix | Part 4 |
| `07-part5-process-evidence.md` | Commit cadence, history, defense | Part 5 |
| `08-benchmark-set-and-ground-truth.md` | BM-1..BM-5 + laser ground truth | Part 2 |
| `09-deliverables-and-reports.md` | Compliance matrix, reproduction bundle, reports | Deliverables |

---

## 2. Standard header every plan uses

Every plan doc begins with this block so dependencies are machine-checkable:

```
Owner:              <doc id> — this doc decides this contract
Provides:           <interface ids owned here>     (see §3)
Consumes:           <interface ids used here>
Must-not-change:    <interface ids this doc must never redefine>
Depends-on:         <doc ids that must land first>
```

---

## 3. Interface ownership matrix — the single source of truth

No interface may be defined in two places. This table is authoritative.

| ID | Interface | Format defined in | Owner doc | Consumers |
|---|---|---|---|---|
| **I1** | Raw capture bundle layout | `01` §6 (mirrors seed data) | `03` | `04b` |
| **I2** | **CIR** (Canonical Intermediate Representation) | `src/scan2plan/cir/model.py` | `04a` | all of `04b`–`04g`, `05`,`08`,`09` |
| **I3** | Published output JSON schema | `docs/schema/plan.schema.json` | `04a` | `04g`,`05`,`09` |
| **I4** | Config schema | `docs/schema/config.schema.json` | `02` | all |
| **I5** | CLI contract (`scan2plan <cmd>`) | `src/scan2plan/cli.py` | `04g` | `05`,`06`,`08`,`09`, walk-in |
| **I6** | Measurement + uncertainty type | `src/scan2plan/cir/measure.py` | `04f` | every producer |
| **I7** | Coordinate frames + units | `01` §4/§5 | `01` | all |
| **I8** | Recon artifact (per-tier) | `src/scan2plan/recon/` | `04b` | `04c`,`04d` |
| **I9** | Benchmark manifest + ground-truth schema | `docs/schema/benchmark.schema.json` | `08` | `04f`,`05`,`09` |

---

## 4. Conflict-prevention rules

- **R1 — One writer per interface.** Only the owner doc may change an interface. Others open an ADR (§5).
- **R2 — Import, don't redefine.** Modules use `cir` types; no local re-definitions of measurements, poses, units.
- **R3 — Schema before code.** `I2`/`I3` are frozen (tagged) before any downstream module is written.
- **R4 — Append-only CIR.** New fields are optional + defaulted; existing fields never change meaning.
- **R5 — Fixture-first integration.** Consumers test against the seed captures (see `00` §7), not invented data.
- **R6 — Determinism by contract.** Any stochastic step declares its seed; cache keys are input hashes (`01` §7).

---

## 5. Change protocol (ADR)

When two plans disagree or an interface must change:
1. Open `docs/adr/NNNN-<slug>.md` stating the conflict, options, and decision.
2. Update the **owner** plan and the interface spec in one commit.
3. Bump the interface version (`I2 v1.1`) and note compatibility in `09`.
4. Downstream plans update their `Consumes:` line only — never the definition.

---

## 6. Build order (DAG)

```
02 foundation ──► 04a (I2/I3 freeze) ──► 04b (I8) ──► 04c ──► 04d ──► 04e ──► 04f (I6) ──► 04g
      │                                                                          ▲
03 capture (I1) ────────────────► 04b                                           │
08 benchmark (I9) ─────────────────────────────────────────────────────────────┘
                                                    └──► 05 head-to-head · 06 fix loop · 09 deliverables
07 process ── continuous (commit cadence from M0)
```

---

## 7. Status legend

`DRAFT` → `REVIEW` → `FROZEN` (interface locked, tag created) → `IMPLEMENTED`.