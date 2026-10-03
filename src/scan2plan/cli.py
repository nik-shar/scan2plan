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
from scan2plan.cir import CIR
from scan2plan.cir.validate import validate_plan
from scan2plan.config import Config, load_config
from scan2plan.geometry import OutlineResult, RoomGeometry, build_outline
from scan2plan.geometry.planes import horizontal_planes
from scan2plan.ingest import ingest_capture, load_bundle
from scan2plan.recon import UnsupportedTierError, run_recon
from scan2plan.render import render_outline_svg, render_room_svg, render_stage_svg
from scan2plan.stitch import run_ablation, run_stitch
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


def _pipeline_s1_s3(
    capture_dir: Path,
    cfg: Config,
    out_dir: Path,
    *,
    stride: int,
    voxel_m: float,
) -> tuple[CIR, OutlineResult | None]:
    """S1 ingest -> S2 recon -> S3 three-stage outline (shared by run/ablate).

    Degenerate clouds produce a recon-only CIR (outline=None) rather than failing
    hard (results-out policy, plan 04 section 3).
    """
    cir = ingest_capture(capture_dir, cfg)
    try:
        cir.recon = run_recon(capture_dir, cir, cfg, out_dir, stride=stride, voxel_m=voxel_m)
    except UnsupportedTierError as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=NOT_IMPLEMENTED_EXIT) from exc

    assert cir.recon.points_ref is not None
    points = np.load(out_dir / cir.recon.points_ref)["points"].astype(np.float64)
    cam = _camera_path(cir)
    try:
        planes = horizontal_planes(points[:, 1])
        if not planes:
            raise ValueError("no floor plane detected")
        floor_y = planes[0].height_m
        ceil_y = planes[1].height_m if len(planes) > 1 else None
        outline = build_outline(
            points,
            cam,
            tier=cir.session.tier,
            floor_y=floor_y,
            ceil_y=ceil_y,
            cfg=cfg,
            room_id="room_0",
        )
    except ValueError as exc:
        typer.secho(
            f"  geometry: {exc}; emitting recon-only plan", fg=typer.colors.YELLOW, err=True
        )
        return cir, None
    cir.rooms = [outline.room]
    cir.surfaces = outline.surfaces
    cir.openings = outline.openings
    cir.measures = outline.measures
    return cir, outline


def _write_stage_json(outline: OutlineResult, out_dir: Path) -> list[Path]:
    """Write the three stage payloads (plan 04i) next to plan.json."""
    written: list[Path] = []
    for name, payload in (
        ("stage1_observed.json", outline.stage1),
        ("stage2_classified.json", outline.stage2),
        ("stage3_final.json", outline.stage3),
    ):
        path = out_dir / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        written.append(path)
    return written


def _resolve_capture_dir(capture: str) -> Path:
    """Resolve ``--capture``: an existing directory, or a capture id (cap_<8hex>).

    Ids are looked up one level deep (``<group>/<capture_id>``, interface I1) in
    the working directory and in ``bench/data``.
    """
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
    """Run S1..S4 (+S9 render) on one capture and write a schema-valid plan.json.

    Damage/concealed/scope stages (S5-S8) land at M5+; ``run`` currently emits a
    CIR with session + frames + recon + single-room geometry + stitch (LiDAR
    tier only at S2).
    """
    cfg = load_config(config, output_dir=str(out) if out is not None else None)
    bundle = load_bundle(capture_dir)
    out_dir = Path(cfg.output_dir) / bundle.capture_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cir, outline = _pipeline_s1_s3(
        Path(capture_dir), cfg, out_dir, stride=stride, voxel_m=voxel_cm / 100.0
    )
    assert cir.recon is not None and cir.recon.points_ref is not None
    points = np.load(out_dir / cir.recon.points_ref)["points"].astype(np.float64)
    stage_paths: list[Path] = []
    svg_paths: list[Path] = []
    svg_path: Path | None = None
    if outline is not None:
        geom = RoomGeometry(
            room=outline.room,
            surfaces=outline.surfaces,
            openings=outline.openings,
            measures=outline.measures,
        )
        svg_path = render_room_svg(geom, out_dir / "plan.svg", title=cir.session.id)
        stage_paths = _write_stage_json(outline, out_dir)
        # One SVG per stage (plan 04i), plus the canonical plan.svg. All inspectable.
        svg_paths = [
            render_outline_svg(
                outline.stage1.get("polygon_xz", []),  # type: ignore[arg-type]
                out_dir / "stage1_observed.svg",
                title=f"{cir.session.id} - stage 1: observed outline (before cleanup)",
                camera_xz=outline.stage1.get("camera_xz", []),  # type: ignore[arg-type]
                note=f"camera travel: {outline.stage1.get('camera_travel_m')} m",
            ),
            render_stage_svg(
                geom,
                outline.stage2.get("regions", []),  # type: ignore[arg-type]
                out_dir / "stage2_classified.svg",
                title=f"{cir.session.id} - stage 2: classified (walls vs removed)",
            ),
            render_room_svg(
                geom,
                out_dir / "stage3_final.svg",
                title=f"{cir.session.id} - stage 3: final wall plan",
            ),
        ]

    # S4 stitch + drift correction (plan 04d); single-room captures stitch trivially.
    cir.stitch = run_stitch(cir, loop_closure=cfg.loop_closure)

    plan_path = out_dir / "plan.json"
    plan_path.write_text(cir.model_dump_json(exclude_none=True, indent=2))
    errors = validate_plan(json.loads(plan_path.read_text()))
    if errors:
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    quality = cir.recon.quality
    typer.echo(f"[{cir.session.id}] tier={cir.session.tier} frames={len(cir.frames)}")
    typer.echo(
        f"  recon: points={points.shape[0]} track_len={int(quality.track_len or 0)} "
        f"coverage={quality.coverage} plane_rms={quality.plane_rms}"
    )
    typer.echo(f"  scale_source={cir.recon.scale_source}")
    if outline is not None:
        area = outline.room.floor_area
        ceil = outline.room.ceiling_height
        area_txt = "n/a" if area is None else f"{area.value:.2f} +/- {area.half_width:.2f} m2"
        ceil_txt = "n/a" if ceil is None else f"{ceil.value:.2f} m"
        n_walls = sum(1 for s in outline.surfaces if s.type == "wall")
        typer.echo(
            f"  room: area={area_txt} ceiling={ceil_txt} walls={n_walls} "
            f"openings={len(outline.openings)}"
        )
        counts = outline.stage2.get("counts", {})
        removed = {k: v for k, v in counts.items() if k != "wall" and v}  # type: ignore[union-attr]
        typer.echo(
            f"  stages: observed={outline.stage1.get('area_m2')} m2 -> "
            f"final={outline.stage3.get('area_m2')} m2 "
            f"edges={outline.stage3.get('n_edges')} method={outline.stage3.get('method')}"
        )
        typer.echo(f"  removed: {removed or 'none'}")
        if outline.warnings:
            for w in outline.warnings:
                typer.secho(f"  warn: {w}", fg=typer.colors.YELLOW, err=True)
    st = cir.stitch
    typer.echo(
        f"  stitch: rooms={len(st.room_transforms)} edges={len(st.edges)} "
        f"closures={len(st.closures)} overlap_ok={st.overlap_ok} unstitched={st.unstitched}"
    )
    typer.echo(f"  wrote {plan_path}")
    if svg_path is not None:
        typer.echo(f"  wrote {svg_path}")
    for p in stage_paths:
        typer.echo(f"  wrote {p}")
    for p in svg_paths:
        typer.echo(f"  wrote {p}")
    typer.echo("  note: damage/scope stages (S5-S8) are pending (M5+).")


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
    """Emit drift on/off footprints from the same code path (G-DRIFT ablation).

    Runs S1-S4 twice with loop closure on/off (plan 04d section 4) and stores the
    two footprints in ``stitch.ablation`` (plan.json) plus a standalone
    ``ablation.json`` under ``out/<capture_id>/``.
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
    logger.info("ablate capture=%s feature=%s base=%s", capture, feature, cfg.loop_closure)
    out_dir = Path(cfg.output_dir) / bundle.capture_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cir, _outline = _pipeline_s1_s3(
        capture_dir, cfg, out_dir, stride=stride, voxel_m=voxel_cm / 100.0
    )

    stitch = run_stitch(cir, loop_closure=cfg.loop_closure)
    stitch.ablation = run_ablation(cir)
    cir.stitch = stitch

    plan_path = out_dir / "plan.json"
    plan_path.write_text(cir.model_dump_json(exclude_none=True, indent=2))
    errors = validate_plan(json.loads(plan_path.read_text()))
    if errors:
        for err in errors:
            typer.secho(f"  - {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    abl_path = out_dir / "ablation.json"
    assert stitch.ablation is not None
    abl_path.write_text(stitch.ablation.model_dump_json(exclude_none=True, indent=2))

    ab = stitch.ablation
    typer.echo(f"[{cir.session.id}] ablation feature=loop_closure (G-DRIFT):")
    typer.echo(
        f"  on : footprint={ab.loop_closure_on.footprint_m2:.3f} m2 "
        f"closure_gap={ab.loop_closure_on.closure_gap_m}"
    )
    typer.echo(f"  off: footprint={ab.off.footprint_m2:.3f} m2 closure_gap={ab.off.closure_gap_m}")
    if len(cir.rooms) < 2:
        typer.echo(
            "  note: fewer than 2 rooms - no inter-room constraints, so on/off "
            "footprints are identical by construction (multi-room set is BM-1, plan 08)."
        )
    typer.echo(f"  wrote {abl_path}")


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
