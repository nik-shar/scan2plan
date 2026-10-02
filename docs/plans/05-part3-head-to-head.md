# 05 — Part 3: Head-to-Head vs Incumbent App

```
Owner:           05
Provides:        head-to-head table
Consumes:        I3 (plan.json), I5 (scan2plan run), I9 (benchmark manifest)
Must-not-change: I1–I9
Depends-on:      04g, 08
```

## 1. Requirement

On **2 benchmark rooms**, compare **our LiDAR-tier output** vs **one consumer scanning app** (free tier OK).
- **Name the app + version**; **submit its export**.
- **One table**, dimension by dimension: our error vs theirs.
- **Beat or tie on ≥ 70% of shared dimensions.**

## 2. Procedure

1. Pick 2 rooms from `08` (prefer the furnished/staged + one plain).
2. Run the incumbent app on the same rooms; export its plan/model.
3. Extract **shared dimensions** (wall lengths, ceiling height, opening widths, area).
4. Ground truth = laser/tape (`08`).
5. Compute `|err_ours|` vs `|err_theirs|` per dimension → tie if diff ≤ 0.5 cm, else win/lose.
6. Report `win_or_tie_share`; must be ≥ 70%.

## 3. Methodological honesty

- Use the **same ground truth** for both.
- **No manual correction** of incumbent export.
- If a dimension exists for one and not the other, mark **not-shared** (excluded, disclosed).

## 4. Deliverables

- `docs/head-to-head.md` (table + app name/version + export path).
- `bench/head_to_head/<room>/<app>_export.*` committed.

## 5. Tasks

| ID | Task | Done when |
|---|---|---|
| H-1 | Choose app + capture both rooms | exports present |
| H-2 | Dimension extraction from exports | shared dims list |
| H-3 | Comparison script (`bench/runner.py`) | table auto-generated |
| H-4 | ≥70% check in CI/report | pass recorded |

## 6. Risks

| Risk | Mitigation |
|---|---|
| Incumbent app export on free tier limited | pick an app whose needed export is free; disclose |
| Unfair comparison (their defaults) | use their best export settings; notes in doc |
| Different measured dimension sets | mark not-shared; disclose |