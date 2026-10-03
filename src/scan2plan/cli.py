"""CLI contract (interface I5).

Command shapes are declared in ``docs/plans/02-foundation-repo-and-infra.md``
section 4 and owned by ``docs/plans/04g-output-render-cli.md`` section 1.

Current state (plan 04i cleanup): stages beyond stage 1 are **being redesigned**
(stage 2/3 moved to ``archive/old_stage23/``). ``scan2plan run`` therefore writes
the stage-1 observed-evidence artifacts and a **stub** ``plan.json`` with
``status="not_computed"`` that still validates against the I3 schema, so the
pipeline completes end-to-end. ``validate`` is fully implemented against I3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import numpy as np
import typer

from scan2plan import __version__
from scan2plan.cir import CIR
from scan2plan.cir.validate import validate_plan
from scan2plan.config import Config, load_config
from scan2plan.geometry import observed_evidence, reconstruct_walls
from scan2plan.geometry.planes import horizontal_planes
from scan2plan.ingest import ingest_capture, load_bundle
from scan2plan.recon import UnsupportedTierError, run_recon
from scan2plan.render import render_evidence_svg, render_walls_svg
from scan2plan.util.logging import get_logger

logger = get_logger("scan2plan.cli")

#: Exit code returned by a command whose stage is not implemented yet.
NOT_IMPLEMENTED_EXIT = 3

app = typer.Typer(
    name="scan2plan",
    help="Phone capture -> stitched whole-property plan + damage assessment.",
    no_args_is_help=True,
    add_completion=False,
)

_CONFIG_OPTION = typer.Option("--config", "-c", help="Path to a YAML config (I4).")


def _version_callback(value: bool) -> None:
    """Print the package version and exit (``--version``)."""
    if value:
        typer.echo(f"scan2plan {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show the scan2plan version and exit.",
        ),
    ] = False,
) -> None:
    """Applied AI Engineer case study: capture -> plan -> damage assessment."""


def _pending(owner: str, stage: str) -> NoReturn:
    """Report a not-yet-implemented stage and exit non-zero (honest skeleton)."""
    typer.secho(
        f"'{stage}' is not implemented yet (planned in docs/plans/{owner}).",
        fg=typer.colors.YELLOW,
        err=True,
    )
    raise typer.Exit(code=NOT_IMPLEMENTED_EXIT)


def _camera_path(cir: CIR) -> np.ndarray:
    """Camera centres (K,3) in world frame from the frame poses (T_wc)."""
    centres = [
        np.array(f.pose, dtype=np.float64).reshape(4, 4)[:3, 3]
        for f in cir.frames
        if f.pose is not None
    ]
    return np.array(centres, dtype=np.float64) if centres else np.empty((0, 3))


def _resolve_capture_dir(capture: str) -> Path:
    """Resolve ``--capture``: an existing directory, or a capture id (cap_<8hex>)."""
    p = Path(capture)
    if p.is_dir():
        return p
    cid = capture.removeprefix("cap_")
    matches = sorted(
        m
        for root in (Path.cwd(), Path.cwd() / "bench" / "data")
        for m in root.glob(f"*/{cid}")
        # Only I1 bundles count (an out/<id>/ dir from a previous run does not).
        if m.is_dir() and (m / "odometry.csv").is_file()
    )
    if len(matches) == 1:
        return matches[0]
    if not matches:
        typer.secho(f"capture '{capture}' not found (no directory or bundle id)", err=True)
    else:
        typer.secho(f"capture id '{capture}' is ambiguous: {matches}", err=True)
    raise typer.Exit(code=2)


def _pipeline_s1_s2(
    capture_dir: Path,
    cfg: Config,
    out_dir: Path,
    *,
    stride: int,
    voxel_m: float,
) -> CIR:
    """S1 ingest -> S2 recon (LiDAR tier). Stages 3+ are being redesigned."""
    cir = ingest_capture(capture_dir, cfg)
    try:
        cir.recon = run_recon(capture_dir, cir, cfg, out_dir, stride=stride, voxel_m=voxel_m)
    except UnsupportedTierError as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=NOT_IMPLEMENTED_EXIT) from exc
    return cir


def _stage1_artifacts(cir: CIR, out_dir: Path, cfg: Config) -> dict[str, object]:
    """Compute stage-1 observed evidence and write its JSON + SVG."""
    assert cir.recon is not None and cir.recon.points_ref is not None
    points = np.load(out_dir / cir.recon.points_ref)["points"].astype(np.float64)
    planes = horizontal_planes(points[:, 1])
    if planes:
        floor_y = planes[0].height_m
        ceil_y = planes[1].height_m if len(planes) > 1 else None
    else:
        # Degenerate cloud: still emit stage-1 artifacts (results-out policy).
        floor_y = float(np.percentile(points[:, 1], 2)) if points.size else 0.0
        ceil_y = None
    unfiltered_path = out_dir / "recon" / "points_unfiltered.npz"
    points_unfiltered = (
        np.load(unfiltered_path)["points"].astype(np.float64) if unfiltered_path.is_file() else None
    )
    stage1 = observed_evidence(
        points, _camera_path(cir), floor_y, ceil_y, cfg, points_unfiltered=points_unfiltered
    )
    if not planes:
        warnings = stage1.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append("no floor plane detected - evidence uses a 2% Y fallback")
    (out_dir / "stage1_observed.json").write_text(
        json.dumps(stage1, indent=2, sort_keys=True) + "\n"
    )
    render_evidence_svg(
        stage1,
        out_dir / "stage1_observed.svg",
        title=f"{cir.session.id} - stage 1: observed evidence",
    )
    return stage1


def _stage2_artifacts(cir: CIR, out_dir: Path, cfg: Config) -> dict[str, object] | None:
    """Reconstruct walls from the stage-1 artifact and write its JSON + SVG.

    Stage 2 is a pure function of the frozen ``stage1_observed.json`` (plan 04i):
    it never touches the raw cloud. Returns ``None`` when the stage-1 artifact is
    absent (nothing to build on).
    """
    stage1_path = out_dir / "stage1_observed.json"
    if not stage1_path.is_file():
        return None
    stage1 = json.loads(stage1_path.read_text())
    stage2 = reconstruct_walls(stage1, cfg, tier=cir.session.tier)
    (out_dir / "stage2_walls.json").write_text(json.dumps(stage2, indent=2, sort_keys=True) + "\n")
    render_walls_svg(
        stage2,
        out_dir / "stage2_walls.svg",
        stage1=stage1,
        title=f"{cir.session.id} - stage 2: wall reconstruction",
    )
    return stage2


def _report_stage2(stage2: dict[str, object] | None, out_dir: Path) -> None:
    """Print the stage-2 wall-reconstruction summary (shared by ``run``/``ablate``)."""
    if stage2 is None:
        return
    cells = stage2.get("cells", {})
    ev = stage2.get("evidence", {})
    typer.echo(
        f"  stage 2 walls: {stage2.get('wall_count')} segments "  # type: ignore[union-attr]
        f"({stage2.get('inferred_count')} inferred), "  # type: ignore[union-attr]
        f"evidence_explained {ev.get('evidence_explained')} "  # type: ignore[union-attr]
        f"(kept {ev.get('evidence_explained_kept')}, "  # type: ignore[union-attr]
        f"cells kept {cells.get('kept')}/{cells.get('input')})"  # type: ignore[union-attr]
    )
    for w in stage2.get("warnings", []):  # type: ignore[union-attr]
        typer.secho(f"  warn: {w}", fg=typer.colors.YELLOW, err=True)
    typer.echo(f"  wrote {out_dir / 'stage2_walls.json'}")
    typer.echo(f"  wrote {out_dir / 'stage2_walls.svg'}")


def _write_stub_plan(cir: CIR, out_dir: Path) -> Path:
    """Write a schema-valid stub plan.json (``status="not_computed"``).

    Stages beyond stage 1 are being redesigned, so the plan carries the stage-1
    sensory ingest + recon only and is explicitly marked not computed.
    """
    cir.status = "not_computed"
    cir.rooms = []
    cir.surfaces = []
    cir.openings = []
    cir.measures = []
    cir.stitch = None
    plan_path = out_dir / "plan.json"
    plan_path.write_text(cir.model_dump_json(exclude_none=True, indent=2))
    errors = validate_plan(json.loads(plan_path.read_text()))
    if errors:
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    return plan_path


@app.command()
def run(
    capture_dir: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=False, help="Capture bundle (I1) directory."),
    ],
    config: Annotated[Path | None, _CONFIG_OPTION] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Output dir (default: config.output_dir)."),
    ] = None,
    stride: Annotated[int, typer.Option("--stride", help="Recon frame stride.")] = 20,
    voxel_cm: Annotated[float, typer.Option("--voxel-cm", help="Recon voxel size (cm).")] = 1.0,
) -> None:
    """Run S1+S2, write the stage-1 observed-evidence artifacts and a stub plan.

    Stages beyond stage 1 are being redesigned (plan 04i): the emitted ``plan.json``
    is schema-valid with ``status="not_computed"`` and carries the sensory ingest +
    recon only. Stage-1 evidence is written to ``stage1_observed.{json,svg}``.
    """
    cfg = load_config(config, output_dir=str(out) if out is not None else None)
    bundle = load_bundle(capture_dir)
    out_dir = Path(cfg.output_dir) / bundle.capture_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cir = _pipeline_s1_s2(Path(capture_dir), cfg, out_dir, stride=stride, voxel_m=voxel_cm / 100)
    assert cir.recon is not None
    try:
        stage1 = _stage1_artifacts(cir, out_dir, cfg)
    except ValueError as exc:
        typer.secho(f"  stage 1: {exc}", fg=typer.colors.YELLOW, err=True)
        stage1 = {"layer_counts": {}, "warnings": [str(exc)]}
    stage2 = _stage2_artifacts(cir, out_dir, cfg)
    plan_path = _write_stub_plan(cir, out_dir)

    quality = cir.recon.quality
    typer.echo(
        f"[{cir.session.id}] tier={cir.session.tier} frames={len(cir.frames)} status=not_computed"
    )
    typer.echo(
        f"  recon: track_len={int(quality.track_len or 0)} coverage={quality.coverage} "
        f"plane_rms={quality.plane_rms}"
    )
    lc = stage1.get("layer_counts", {})
    typer.echo(
        f"  stage 1 evidence: walls={lc.get('wall_cells')} "  # type: ignore[union-attr]
        f"floor={lc.get('floor_cells')} free={lc.get('camera_free_space')}"
    )
    for w in stage1.get("warnings", []):  # type: ignore[union-attr]
        typer.secho(f"  warn: {w}", fg=typer.colors.YELLOW, err=True)
    typer.echo(f"  wrote {out_dir / 'stage1_observed.json'}")
    typer.echo(f"  wrote {out_dir / 'stage1_observed.svg'}")
    _report_stage2(stage2, out_dir)
    typer.echo(f"  wrote {plan_path}")
    typer.echo("  note: stages beyond 2 (closing/stitch/damage) are being redesigned.")


@app.command()
def ingest(
    capture_dir: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=False, help="Capture bundle (I1) directory."),
    ],
    config: Annotated[Path | None, _CONFIG_OPTION] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Output dir (default: config.output_dir)."),
    ] = None,
) -> None:
    """Ingest one capture bundle into the CIR (stage S1 only)."""
    cfg = load_config(config, output_dir=str(out) if out is not None else None)
    bundle = load_bundle(capture_dir)
    cir = ingest_capture(capture_dir, cfg)
    out_dir = Path(cfg.output_dir) / bundle.capture_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "cir.json"
    path.write_text(cir.model_dump_json(exclude_none=True, indent=2))
    typer.echo(f"[{cir.session.id}] tier={cir.session.tier} frames={len(cir.frames)} -> {path}")


@app.command()
def ablate(
    capture: Annotated[
        str, typer.Option("--capture", help="Capture id (cap_<8hex>) or bundle path.")
    ],
    feature: Annotated[
        str, typer.Option("--feature", help="Feature to toggle (04d).")
    ] = "loop_closure",
    config: Annotated[Path | None, _CONFIG_OPTION] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Output dir (default: config.output_dir)."),
    ] = None,
    stride: Annotated[int, typer.Option("--stride", help="Recon frame stride.")] = 20,
    voxel_cm: Annotated[float, typer.Option("--voxel-cm", help="Recon voxel size (cm).")] = 1.0,
) -> None:
    """Drift ablation (G-DRIFT) - pending the stage 2/3 redesign.

    The ablation needs room geometry to stitch, which is being redesigned (plan
    04i). ``ablate`` now emits the stage-1 evidence + a stub plan so the capture is
    still inspectable, and reports honestly that the ablation is not computed.
    """
    if feature != "loop_closure":
        typer.secho(
            f"unknown feature '{feature}' (only 'loop_closure' exists, plan 04d)",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    cfg = load_config(config, output_dir=str(out) if out is not None else None)
    capture_dir = _resolve_capture_dir(capture)
    bundle = load_bundle(capture_dir)
    out_dir = Path(cfg.output_dir) / bundle.capture_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cir = _pipeline_s1_s2(capture_dir, cfg, out_dir, stride=stride, voxel_m=voxel_cm / 100)
    try:
        _stage1_artifacts(cir, out_dir, cfg)
    except ValueError as exc:
        typer.secho(f"  stage 1: {exc}", fg=typer.colors.YELLOW, err=True)
    _report_stage2(_stage2_artifacts(cir, out_dir, cfg), out_dir)
    _write_stub_plan(cir, out_dir)
    typer.secho(
        "  ablation not computed: drift ablation depends on the stage 3+ rebuild "
        "(plan 04i). Wrote stage-1 evidence + stage-2 walls + stub plan instead.",
        fg=typer.colors.YELLOW,
        err=True,
    )


@app.command()
def bench(
    tier: Annotated[
        str | None,
        typer.Option("--tier", help="Restrict to one tier: photos|video|lidar."),
    ] = None,
    config: Annotated[Path | None, _CONFIG_OPTION] = None,
) -> None:
    """Run the benchmark harness and compute every gate (plan 08)."""
    load_config(config)
    logger.info("bench tier=%s", tier)
    _pending("08", "bench (gates BM-1..BM-5)")


@app.command()
def report(
    config: Annotated[Path | None, _CONFIG_OPTION] = None,
) -> None:
    """Build the benchmark / report tables (plan 09)."""
    load_config(config)
    _pending("09", "report")


@app.command()
def validate(
    plan_json: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, help="A produced plan.json (I3)."),
    ],
    schema: Annotated[
        Path | None,
        typer.Option("--schema", help="Override the I3 schema path."),
    ] = None,
) -> None:
    """Validate a plan.json against the published I3 schema (plan 04a, task C-4)."""
    data = json.loads(plan_json.read_text())
    errors = validate_plan(data, schema_path=schema)
    if errors:
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED, err=True)
        typer.secho(f"INVALID: {plan_json} ({len(errors)} error(s))", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho(f"valid: {plan_json}", fg=typer.colors.GREEN)


def main() -> None:
    """Console-script entry point (``scan2plan = scan2plan.cli:main``)."""
    app()


if __name__ == "__main__":
    main()
