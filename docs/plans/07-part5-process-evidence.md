# 07 — Part 5: Process Evidence

```
Owner:           07
Provides:        commit-cadence policy + defense kit
Consumes:        every doc (history)
Must-not-change: I1–I9
Depends-on:      —
```

## 1. Requirement

"Commit as you work. We read the history." A repo that **materialises in one or two commits** scores **zero**
here and casts suspicion on the narrative. Not commits/day — but the history **could belong to the person
who built the thing**.

## 2. Policy (start now — repo is not yet git)

- **`git init` at M0** (`02` F-1) with the brief + plans as the first commit.
- **Commit per task** (the `T-x` ids in every plan are commit-sized).
- Conventional messages: `feat(04c): wall plane extraction`, `fix(04d): overlap resolution`.
- **Tags** mark interfaces/milestones: `iface-v1.0`, `m1`, `fix-before`, `fix-after`.
- Branches for the fix loop; merge with a readable diff.
- Do **not** rewrite history; let the record show iteration.

## 3. History ↔ plan traceability

- Every commit references a plan doc + task id → a reviewer can map history to the build order (`README` §6).
- `CHANGELOG.md` summarizing milestones; keep it honest about dead ends.

## 4. Defense kit (tools closed)

Prepare a `docs/defense.md` with:
- Architecture walkthrough (one diagram), tier design, device matrix.
- Drift method + ablation evidence; error budget; calibration.
- **Every design decision + its alternative** (pull from each plan's Decisions/Risks).

## 5. Tasks

| ID | Task | Done when |
|---|---|---|
| PR-1 | `git init` + first commit | history exists |
| PR-2 | Commit-per-task discipline | ongoing |
| PR-3 | Tags for interfaces/milestones | applied |
| PR-4 | `CHANGELOG.md` | updated per milestone |
| PR-5 | `docs/defense.md` | covers every decision |

## 6. Risks

| Risk | Mitigation |
|---|---|
| Big-bang commit | commit per task from M0 |
| History unrelated to plan | reference doc+task ids in messages |
| Undefendable decisions | write alternatives in plans now |