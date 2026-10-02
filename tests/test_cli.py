"""Tests for the I5 CLI skeleton (plan 02 task F-4, contract in plan 04g section 1)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scan2plan import __version__
from scan2plan.cli import NOT_IMPLEMENTED_EXIT, app

runner = CliRunner()

COMMANDS = ("run", "ingest", "ablate", "bench", "report", "validate")


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in COMMANDS:
        assert command in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_bare_invocation_shows_usage() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_run_reports_pending(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT
    assert "not implemented" in result.output.lower()


def test_run_exercises_config_and_out_options(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", str(tmp_path), "--out", "elsewhere"])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT


def test_run_requires_existing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    result = runner.invoke(app, ["run", str(missing)])
    assert result.exit_code != 0
    assert result.exit_code != NOT_IMPLEMENTED_EXIT


def test_ingest_reports_pending(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ingest", str(tmp_path)])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT


def test_ablate_reports_pending() -> None:
    result = runner.invoke(app, ["ablate", "--capture", "cap_c00a170fe1"])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT


def test_ablate_requires_capture() -> None:
    result = runner.invoke(app, ["ablate"])
    assert result.exit_code != 0
    assert result.exit_code != NOT_IMPLEMENTED_EXIT


def test_bench_reports_pending() -> None:
    result = runner.invoke(app, ["bench", "--tier", "lidar"])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT


def test_report_reports_pending() -> None:
    result = runner.invoke(app, ["report"])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT


def test_validate_reports_pending(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    result = runner.invoke(app, ["validate", str(plan)])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT
