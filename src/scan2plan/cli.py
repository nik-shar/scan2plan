"""CLI contract (interface I5).

Command shapes are declared in ``docs/plans/02-foundation-repo-and-infra.md``
section 4 and owned (filled in) by ``docs/plans/04g-output-render-cli.md``
section 1.

This module is the **M0 skeleton plus the M2 ``validate`` command**: every command
of the contract is registered so ``scan2plan --help`` lists them, arguments are
validated, and the I4 config is loaded. Pipeline stages are placeholders that point
at the owning plan doc (they land at milestones M1..M9); ``validate`` is fully
implemented against interface I3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import numpy as np
import typer

from scan2plan import __version__
from scan2plan.cir.validate import validate_plan
from scan2plan.config import load_config
from scan2plan.geometry import extract_room
from scan2plan.ingest import ingest_capture, load_bundle
from scan2plan.recon import UnsupportedTierError, run_recon
from scan2plan.render import render_room_svg
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
    """Run ingest + recon (S1+S2) on one capture and write a schema-valid plan.json.

    Geometry/stitch/damage stages (S3+) land at M3+; for now ``run`` emits a CIR with
    session + frames + recon (LiDAR tier only).
    """
    cfg = load_config(config, output_dir=str(out) if out is not None else None)
    bundle = load_bundle(capture_dir)
    cir = ingest_capture(capture_dir, cfg)
    out_dir = Path(cfg.output_dir) / bundle.capture_id
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        cir.recon = run_recon(
            Path(capture_dir), cir, cfg, out_dir, stride=stride, voxel_m=voxel_cm / 100.0
        )
    except UnsupportedTierError as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=NOT_IMPLEMENTED_EXIT) from exc

    # S3 geometry (single-room) + S9 render. Degenerate clouds emit a recon-only
    # plan rather than failing hard (results-out policy, plan 04 section 3).
    recon = cir.recon
    points = np.load(out_dir / str(recon.points_ref))["points"].astype(np.float64)
    try:
        geom = extract_room(points, tier=cir.session.tier, seed=cfg.seed, room_id="room_0")
    except ValueError as exc:
        typer.secho(
            f"  geometry: {exc}; emitting recon-only plan", fg=typer.colors.YELLOW, err=True
        )
        geom = None
    if geom is not None:
        cir.rooms = [geom.room]
        cir.surfaces = geom.surfaces
        cir.openings = geom.openings
        cir.measures = geom.measures
        svg_path: Path | None = render_room_svg(geom, out_dir / "plan.svg", title=cir.session.id)
    else:
        svg_path = None

    plan_path = out_dir / "plan.json"
    plan_path.write_text(cir.model_dump_json(exclude_none=True, indent=2))
    errors = validate_plan(json.loads(plan_path.read_text()))
    if errors:
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    quality = recon.quality
    typer.echo(f"[{cir.session.id}] tier={cir.session.tier} frames={len(cir.frames)}")
    typer.echo(
        f"  recon: points={points.shape[0]} track_len={int(quality.track_len or 0)} "
        f"coverage={quality.coverage} plane_rms={quality.plane_rms}"
    )
    typer.echo(f"  scale_source={recon.scale_source}")
    if geom is not None:
        area = geom.room.floor_area
        ceil = geom.room.ceiling_height
        area_txt = "n/a" if area is None else f"{area.value:.2f} m2"
        ceil_txt = "n/a" if ceil is None else f"{ceil.value:.2f} m"
        n_walls = sum(1 for s in geom.surfaces if s.type == "wall")
        typer.echo(
            f"  room: area={area_txt} ceiling={ceil_txt} walls={n_walls} "
            f"openings={len(geom.openings)}"
        )
    typer.echo(f"  wrote {plan_path}")
    if svg_path is not None:
        typer.echo(f"  wrote {svg_path}")
    typer.echo("  note: stitch/damage/scope stages (S4-S8) are pending (M4+).")


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
    capture: Annotated[str, typer.Option("--capture", help="Capture id (cap_<8hex>).")],
    feature: Annotated[
        str, typer.Option("--feature", help="Feature to toggle (04d).")
    ] = "loop_closure",
    config: Annotated[Path | None, _CONFIG_OPTION] = None,
) -> None:
    """Emit drift on/off footprints from the same code path (G-DRIFT ablation)."""
    cfg = load_config(config)
    logger.info("ablate capture=%s feature=%s base=%s", capture, feature, cfg.loop_closure)
    _pending("04d", "ablate (loop-closure ablation)")


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
