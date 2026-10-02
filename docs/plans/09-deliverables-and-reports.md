# 09 — Deliverables, Reports & Compliance

```
Owner:           09
Provides:        compliance matrix, reproduction bundle, reports, disclosure list
Consumes:        all artifacts (I1–I9)
Must-not-change: I1–I9
Depends-on:      all
```

## 1. The 8 deliverables → owner mapping

| # | Deliverable | Plan doc | Artifact |
|---|---|---|---|
| 1 | **Compliance matrix** (req→path→artifact→status) | `09` | `docs/compliance-matrix.md` |
| 2 | **Capture route** + **device matrix** | `03` | `docs/protocol.md`, `docs/device-matrix.md` |
| 3 | **Repo + README** (<15 min, one command/capture) | `02`,`04g` | `README.md`, `scripts/` |
| 4 | **Reproduction bundle** (regenerate every number) | `09`,`06` | `repro/` + `run.sh` |
| 5 | **Benchmark report** (gates/tiers/repeatability/H2H/timing) | `08` | `docs/benchmark-report.md` |
| 6 | **Fix loop bundle** | `06` | `messages/fix_loop/` |
| 7 | **Technical report (≤6 pages)** | `09` | `docs/technical-report.pdf` |
| 8 | **Raw benchmark data** | `08` | GP/LFS + `bench/ground_truth/` |

## 2. Compliance matrix format

| Requirement ID | Requirement | File path | Artifact | Status |
|---|---|---|---|---|
| CAP-3.1 | photos tier 2–8 stills/room | `src/scan2plan/ingest/photos.py` | code+test | ⬜/🟡/✅ |
| OUT-2 | stitched multi-room plan | `src/scan2plan/stitch/` | plan.svg | ⬜ |
| G-DRIFT | drift correction + ablation | `src/scan2plan/stitch/ablate.py` | ablation figure | ⬜ |
| ... | (fill from every plan's IDs) | | | |

Coverage % is scored (10%) — keep it complete and honest.

## 3. Reproduction bundle (Deliverable 4)

- `repro/README.md` + `scripts/reproduce.sh`: from raw inputs **regenerate every reported number**.
- **Cached model outputs replay deterministically AND the live path also runs** (walk-in).
- Pinned deps + lockfile; `scripts/fetch_weights.sh` for weights (not committed).

## 4. Technical report (≤6 pages) — required sections

Architecture · tier design + device matrix · **drift handling** · **error budget** ·
**calibration analysis** · **fix loop story** · **known failure modes**. Page cap is deliberate → prefer
figures over prose; score the engineering.

## 5. Disclosure list (required by constraints)

| Model/API/dataset | Version | Licence | Where used | Fetch/on-device |
|---|---|---|---|---|
| (fill each) | | | | |

## 6. Tasks

| ID | Task | Done when |
|---|---|---|
| A-1 | Compliance matrix seeded from all plan IDs | every ID has a row |
| A-2 | Reproduction bundle | regenerates a reported number |
| A-3 | Benchmark report | all gate tables |
| A-4 | Technical report ≤6 pp | reviewed |
| A-5 | Disclosure list | complete |

## 7. Risks

| Risk | Mitigation |
|---|---|
| Compliance gaps at the end | grow matrix as tasks land |
| Repro bundle not deterministic | hash + seeds + twice-verify |
| Report > 6 pages | figures; cut prose |
| Undisclosed model | CI grep for model names vs disclosure list |