"""CLI contract (interface I5).

Command shapes are declared in ``docs/plans/02-foundation-repo-and-infra.md``
section 4 and owned (filled in) by ``docs/plans/04g-output-render-cli.md``
section 1.

This module is the **M0 skeleton**: every command of the contract is registered
so ``scan2plan --help`` lists them, arguments are validated, and the I4 config is
loaded. Each stage body is a placeholder that points at the plan doc which will
implement it (stages land at their milestones M1..M9).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from scan2plan import __version__
from scan2plan.config import load_config
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
) -> None:
    """Run the full pipeline S1..S9 on one capture (one command per capture)."""
    cfg = load_config(config, output_dir=str(out) if out is not None else None)
    logger.info("run capture=%s tier=%s out=%s", capture_dir, cfg.tier, cfg.output_dir)
    _pending("04g", "run (ingest -> ... -> output)")


@app.command()
def ingest(
    capture_dir: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=False, help="Capture bundle (I1) directory."),
    ],
    config: Annotated[Path | None, _CONFIG_OPTION] = None,
) -> None:
    """Ingest one capture bundle into the CIR (stage S1 only)."""
    cfg = load_config(config)
    logger.info("ingest capture=%s tier=%s", capture_dir, cfg.tier)
    _pending("04b", "ingest (S1)")


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
    """Validate a plan.json against the published I3 schema."""
    logger.info("validate plan=%s schema=%s", plan_json, schema)
    _pending("04a", "validate (I3 plan schema)")


def main() -> None:
    """Console-script entry point (``scan2plan = scan2plan.cli:main``)."""
    app()


if __name__ == "__main__":
    main()
