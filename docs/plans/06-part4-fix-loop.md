# 06 — Part 4: The Fix Loop (25%)

```
Owner:           06
Provides:        fix declaration + before/after bundle
Consumes:        I5 (scan2plan run/bench), I3, I9, drift ablation (04d)
Must-not-change: I1–I9
Depends-on:      04g, 08
```

## 1. Two-phase requirement

**Phase A — declare (one page), before shipping:**
1. The **single worst-performing gate** in our own benchmark, with the failing number.
2. **Root-cause hypothesis + evidence**.
3. The **fix we intend to ship** and the **predicted number** after it.

**Phase B — ship it.** Final submission: **before run**, **after run**, both **regenerable by them**, readable diff.

## 2. Scoring ladder (design to hit full marks)

| Outcome | Marks |
|---|---|
| correct root cause + shipped fix + gate **fail→pass** | **full** |
| correct root cause + shipped fix + movement short of gate | majority (explain shortfall) |
| prediction badly wrong | honesty marks only |
| analysis, no shipped fix | **zero** |
| fix, no regenerable before/after | **zero** |

→ Therefore: **always ship a fix**, and **always keep both runs regenerable** from input hashes.

## 3. Reproducibility harness

- `scan2plan run` on frozen inputs ⇒ identical numbers (`01` §7 caching).
- `messages/fix_loop/before/` and `after/` each contain `plan.json`, `bench.json`, and a `run.sh`.
- `diff` = `git diff` between `fix-before` and `fix-after` tags (readable, small).

## 4. Candidate worst gates (ranked by plausible failure)

Given the brief's known failure clusters, the likely worst gate is one of:
1. **G-PSTITCH** (photo-tier whole-property stitch) — hardest.
2. **G-OPEN** (opening detection; misses+phantoms).
3. **G-CEIL spread** (repeatability across captures).
4. **G-DRIFT** (multi-room accumulated drift).
Pick the one our benchmark actually flags **worst** — not the convenient one.

## 5. Process

1. After M7, compute all gates (`08`); identify the max-violation gate.
2. Write `docs/fix-declaration.md` (Phase A) **and commit early** (Part 5 rewards evolution).
3. Implement the fix on a branch; tag `fix-before` / `fix-after`.
4. Regenerate both runs; produce the diff + shortfall/overshoot narrative.

## 6. Tasks

| ID | Task | Done when |
|---|---|---|
| X-1 | Identify worst gate w/ number | declaration drafted |
| X-2 | Root cause + evidence | evidence committed |
| X-3 | Prediction recorded | in declaration |
| X-4 | Ship fix | `fix-after` tag; gate re-run |
| X-5 | Before/after bundles + diff | regenerable by reviewer |

## 7. Risks

| Risk | Mitigation |
|---|---|
| Fix doesn't move the gate | keep scope tight; measure early |
| Regeneration non-deterministic | hashing + seeds; verify twice |
| Declaration written at the end | commit declaration early (Part 5) |