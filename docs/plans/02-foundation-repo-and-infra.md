# 02 — Foundation: Repo, Infra, CLI Skeleton

```
Owner:           02
Provides:        I4 (config schema)
Consumes:        I5 (imports CLI stub), I7
Must-not-change: I1, I2, I3, I6, I8, I9
Depends-on:      01
```

Everything here must land at **M0** so all later plans share one skeleton.

## 1. Repo layout (created here)

```
repo/
  Applied_AI_Case_Study.pdf        # brief (existing)
  single_room/ single_scan_*       # seed captures (existing, git-ignored via .gitattributes/LFS)
  docs/
    plans/                         # this plan suite
    schema/{plan.schema.json, config.schema.json, benchmark.schema.json}
    protocol.md                    # one-page capture protocol (from 03)
    adr/
  src/scan2plan/
    __init__.py
    cli.py                         # I5 skeleton (owns later in 04g)
    config.py                      # I4 pydantic config
    cir/                           # I2 (frozen in 04a)
    ingest/ recon/ geometry/ stitch/ damage/ scope/ uncertainty/ render/
    util/{seed.py, hashing.py, logging.py, frames.py}
  bench/{data/, ground_truth/, runner.py, manifest.json}
  tests/
  scripts/{fetch_weights.sh, bootstrap.sh, run_capture.sh}
  pyproject.toml  ruff.toml  mypy.ini  .gitignore  README.md
```

## 2. Bootstrap conventions

- `scripts/bootstrap.sh`: create venv, `pip install -e .`, run `pytest -q`, print next steps.
- **Clean-machine target: < 15 min** to first run (Deliverable 3). Record measured time in `09`.
- `scripts/run_capture.sh <capture_dir>` = thin wrapper over `scan2plan run` (one command per capture).

## 3. Dependencies (pinned; all local)

| Concern | Library |
|---|---|
| data/typing | pydantic v2, numpy, scipy |
| geometry | open3d, shapely |
| CV / SfM | opencv-python, pycolmap (or GLOMAP) |
| LiDAR ingest | pillow (+ record3d only if `.r3d` inputs appear) |
| models | torch (segmentation/depth/CLIP — owned by 04e/04b) |
| pose graph | scipy least_squares (default) or gtsam (optional) |
| schema | jsonschema |
| render | svgwrite / matplotlib |
| CLI | typer (or argparse if typer unavailable) |
| QA | pytest, ruff, mypy |

`pyproject.toml` pins exact versions; a lockfile is committed for reproduction.

## 4. CLI skeleton (`I5`) — shapes only, filled by `04g`

```
scan2plan run <capture_dir> [--config ...]     # ingest→...→output (one command)
scan2plan ingest <capture_dir>
scan2plan bench [--tier ...]
scan2plan report
scan2plan ablate --capture <id> --feature loop_closure   # drift on/off (04d)
scan2plan validate <plan.json>                 # schema check (04a)
```

## 5. CI (blocking)

1. `ruff check` + `ruff format --check`
2. `mypy --strict src/scan2plan/cir`
3. `pytest -q`
4. **schema validation** of `docs/schema/*.json` and of any produced `plan.json`
5. smoke test: `scan2plan run` on the smallest seed capture (downsampled) produces valid `plan.json`

## 6. `.gitignore` / data policy

- Ignore `out/`, `*.cache`, venv, model weights (`weights/`).
- **Seed captures**: prefer **Git LFS** for `*.mp4/*.png` or document them as externally fetched via
  `scripts/fetch_weights.sh`. They are large (~44–252 MB each) → never in plain git history.
- `bench/data` ground truth is small → committed.

## 7. Tasks

| ID | Task | Done when |
|---|---|---|
| F-1 | `git init` + initial commit (with PDF + plans) | history started (Part 5) |
| F-2 | Create layout + `pyproject.toml` + pins | `pip install -e .` works |
| F-3 | `I4` config schema + pydantic loader | unknown keys rejected |
| F-4 | CLI skeleton (`I5` shapes) | `scan2plan --help` lists cmds |
| F-5 | `util/{seed,hashing,frames}.py` | deterministic seed + hash helpers tested |
| F-6 | CI config | all 5 checks run locally |
| F-7 | bootstrap script + README | clean-machine run measured < 15 min |

## 8. Acceptance (M0)

- `scan2plan --help` works on a fresh clone after `scripts/bootstrap.sh`.
- CI green on the skeleton.
- `I4` schema committed (`config.schema.json`) and mirrors §8 of doc `01`.