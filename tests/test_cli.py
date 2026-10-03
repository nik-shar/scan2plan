"""Tests for the I5 CLI skeleton (plan 02 task F-4, contract in plan 04g section 1)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from scan2plan import __version__
from scan2plan.cir.validate import validate_plan
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


def test_run_writes_valid_plan(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=2, shape=(8, 8))
    out_dir = tmp_path / "out"
    result = runner.invoke(app, ["run", str(cap), "--out", str(out_dir)])
    assert result.exit_code == 0
    plan = out_dir / cap.name / "plan.json"
    assert plan.is_file()
    # the written plan is schema-valid (I3) including referential integrity
    assert validate_plan(json.loads(plan.read_text())) == []
    # recon artifacts were written and referenced
    data = json.loads(plan.read_text())
    recon_ref = data["recon"]["points_ref"]
    assert (out_dir / cap.name / recon_ref).is_file()


def test_run_exercises_config_and_out_options(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=2)
    out_dir = tmp_path / "custom_out"
    result = runner.invoke(app, ["run", str(cap), "--out", str(out_dir), "--stride", "1"])
    assert result.exit_code == 0
    assert (out_dir / cap.name / "plan.json").is_file()


def test_ingest_writes_cir(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=2)
    out_dir = tmp_path / "out"
    result = runner.invoke(app, ["ingest", str(cap), "--out", str(out_dir)])
    assert result.exit_code == 0
    cir_path = out_dir / cap.name / "cir.json"
    assert cir_path.is_file()
    data = json.loads(cir_path.read_text())
    assert data["session"]["tier"] == "lidar"
    assert len(data["frames"]) == 2


def test_run_requires_existing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    result = runner.invoke(app, ["run", str(missing)])
    assert result.exit_code != 0
    assert result.exit_code != NOT_IMPLEMENTED_EXIT


def test_ablate_unknown_capture_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ablate", "--capture", "cap_doesnotexist"])
    assert result.exit_code == 2  # resolution failure, not a pending stub
    assert result.exit_code != NOT_IMPLEMENTED_EXIT


def test_ablate_emits_stage1_and_stub_plan(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=2)
    out_dir = tmp_path / "out"
    result = runner.invoke(app, ["ablate", "--capture", str(cap), "--out", str(out_dir)])
    assert result.exit_code == 0
    # stages beyond 1 are being redesigned -> a stub plan (not_computed) + evidence
    plan = out_dir / cap.name / "plan.json"
    assert plan.is_file()
    assert json.loads(plan.read_text())["status"] == "not_computed"
    assert (out_dir / cap.name / "stage1_observed.json").is_file()


def test_ablate_rejects_unknown_feature(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=2)
    result = runner.invoke(app, ["ablate", "--capture", str(cap), "--feature", "nope"])
    assert result.exit_code == 2


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


def test_run_writes_stub_plan(make_lidar_bundle, tmp_path: Path) -> None:
    cap = make_lidar_bundle(tmp_path, n_frames=2)
    out_dir = tmp_path / "out"
    result = runner.invoke(app, ["run", str(cap), "--out", str(out_dir)])
    assert result.exit_code == 0
    plan = out_dir / cap.name / "plan.json"
    data = json.loads(plan.read_text())
    assert data["status"] == "not_computed"  # stages beyond 1 are being redesigned
    assert validate_plan(data) == []
    assert (out_dir / cap.name / "stage1_observed.json").is_file()


def test_validate_accepts_valid_plan(tmp_path: Path, valid_plan_dict: dict) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(valid_plan_dict))
    result = runner.invoke(app, ["validate", str(plan)])
    assert result.exit_code == 0
    assert "valid" in result.output.lower()


def test_validate_rejects_invalid_plan(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{}")  # missing required session/provenance
    result = runner.invoke(app, ["validate", str(plan)])
    assert result.exit_code == 1


def test_validate_rejects_broken_reference(tmp_path: Path, valid_plan_dict: dict) -> None:
    valid_plan_dict["damages"][0]["surface_id"] = "ghost"
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(valid_plan_dict))
    result = runner.invoke(app, ["validate", str(plan)])
    assert result.exit_code == 1
