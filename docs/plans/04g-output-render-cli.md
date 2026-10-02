# 04g — Output, Rendering & CLI (one command per capture)

```
Owner:           04g
Provides:        I5 (CLI contract), plan.svg + report.html emit
Consumes:        full CIR (I2), I3 schema, I6
Must-not-change: I1, I2, I3, I4, I8
Depends-on:      04a–04f
```

Delivers OUT-7 (**one command per capture**), OUT-8 (**JSON to schema**), OUT-9 (**rendered plan**).

## 1. CLI contract (I5)

```
scan2plan run <capture_dir> [--config cfg.yaml] [--out out/]
    # tier auto-detected (01 §6); runs S1..S9; writes out/<capture_id>/
scan2plan ingest <capture_dir>            # S1 only
scan2plan ablate --capture <id> --feature loop_closure
scan2plan bench [--tier photos|video|lidar]
scan2plan report                           # build benchmark/report tables
scan2plan validate <plan.json>             # I3 schema check
```
- Exit 0 + `plan.json` + `plan.svg` + `report.html` on success.
- Deterministic: same input + config ⇒ byte-identical `plan.json` (modulo timing fields).

## 2. Emit

| Artifact | Path | Notes |
|---|---|---|
| `plan.json` | `out/<cap>/plan.json` | validates against `I3` (blocking) |
| `plan.svg` | `out/<cap>/plan.svg` | stitched plan, dimensions, openings, damage overlay |
| `report.html` | `out/<cap>/report.html` | per-measurement table + CIs + ablation thumbnails |
| `cache/` | `out/<cap>/cache/` | input-hash keyed |

## 3. SVG render spec (OUT-9)

- Plan-view (stitched world XY), **metres**, walls as filled polygons, openings as gaps with labels.
- Dimension strings = `value ± ci` (e.g. `3.42 ± 0.01 m`).
- Damage regions tinted by class with legend; concealed flags marked.
- One file, no external assets (self-contained for the report).

## 4. `report.html` content

- Summary metrics; per-room table (ceiling, area, walls); openings table; damage + scope tables.
- **Ablation** thumbnails (drift on/off).
- Calibration coverage summary (links `04f`).

## 5. Tasks

| ID | Task | Done when |
|---|---|---|
| O-1 | `run` end-to-end wiring | seed → plan.json+svg |
| O-2 | Schema emit + validate | CI validates every run |
| O-3 | SVG renderer | dimensioned stitched plan |
| O-4 | HTML report | tables + ablation |
| O-5 | Determinism test | two runs byte-identical |

## 6. Risks

| Risk | Mitigation |
|---|---|
| Non-deterministic JSON (dict order) | sorted keys; fixed float formatting |
| SVG unreadable | review with a homeowner-eye checklist |
| Command needs extra flags | defaults so plain `run` works |