"""Build a conformant interface-I1 capture bundle from a raw LiDAR-logger export.

Plan 03 (task P1-3): the capture route is a stock LiDAR logger whose export is turned
into an ``I1`` bundle (``docs/plans/01`` section 6) that ``scan2plan run`` consumes
unchanged. This module normalises the common export shapes and **proves** the result by
re-loading it with ``scan2plan.ingest.bundle.load_bundle``:

    depth/            uint16 PNG, 256x192, millimetres (or depth_m/ in metres)
    confidence/       uint8 PNG {0,1,2}          (optional -> synthesised as all-2)
    odometry.csv      timestamp,frame,x,y,z,qx,qy,qz,qw[,fx,fy,cx,cy]
    camera_matrix.csv 3x3 K                      (or fx..cy taken from odometry)
    imu.csv           optional (copied through; not used by the pipeline)
    rgb.mp4           optional (the LiDAR pipeline reads depth + poses only)
    meta.json         device / iOS / tool / rooms_expected (written here)

Usage:
    python -m scan2plan.ingest.build <raw_dir> --out <bundles_dir> [options]
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from scan2plan.ingest.bundle import DEPTH_SHAPE, load_bundle

#: Canonical I1 odometry columns (interface I1, docs/plans/01 section 6).
ODOMETRY_COLUMNS = [
    "timestamp",
    "frame",
    "x",
    "y",
    "z",
    "qx",
    "qy",
    "qz",
    "qw",
    "fx",
    "fy",
    "cx",
    "cy",
    "distortion_center_x",
    "distortion_center_y",
]


class BundleBuildError(ValueError):
    """Raised when a raw export cannot be turned into a valid I1 bundle."""


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open() as fh:
        return [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def _camera_matrix(raw: Path) -> np.ndarray | None:
    """Read camera_matrix.csv (3x3 K), or None when absent."""
    path = raw / "camera_matrix.csv"
    if not path.is_file():
        return None
    k = np.loadtxt(path, delimiter=",", dtype=np.float64)
    if k.shape != (3, 3):
        raise BundleBuildError(f"camera_matrix.csv must be 3x3, got {k.shape}")
    return k


def _write_odometry(rows: list[dict[str, str]], k: np.ndarray, out: Path) -> None:
    """Write canonical odometry.csv, filling intrinsics from K when a row omits them."""
    with out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(ODOMETRY_COLUMNS)
        for r in rows:
            for col in ("timestamp", "frame", "x", "y", "z", "qx", "qy", "qz", "qw"):
                if not r.get(col):
                    raise BundleBuildError(f"odometry row missing '{col}': {r}")
            fx = r.get("fx") or str(float(k[0, 0]))
            fy = r.get("fy") or str(float(k[1, 1]))
            cx = r.get("cx") or str(float(k[0, 2]))
            cy = r.get("cy") or str(float(k[1, 2]))
            writer.writerow(
                [
                    r["timestamp"],
                    r["frame"],
                    r["x"],
                    r["y"],
                    r["z"],
                    r["qx"],
                    r["qy"],
                    r["qz"],
                    r["qw"],
                    fx,
                    fy,
                    cx,
                    cy,
                    r.get("distortion_center_x", ""),
                    r.get("distortion_center_y", ""),
                ]
            )


def _depth_scale(depth_units: str) -> float:
    if depth_units == "mm":
        return 1.0
    if depth_units == "m":
        return 1000.0
    raise BundleBuildError(f"depth-units must be 'mm' or 'm', got {depth_units!r}")


def _write_depth(src: Path, out: Path, scale: float, warnings: list[str]) -> set[str]:
    """Copy/normalise depth PNGs to uint16 millimetres; return the frame stems."""
    out.mkdir(parents=True, exist_ok=True)
    frames: set[str] = set()
    for png in sorted(src.glob("*.png")):
        img = np.asarray(Image.open(png))
        if img.shape != DEPTH_SHAPE:
            raise BundleBuildError(
                f"{png.name}: depth is {img.shape[1]}x{img.shape[0]}, expected "
                f"{DEPTH_SHAPE[1]}x{DEPTH_SHAPE[0]} (the app export grid); "
                "do not rescale depth - re-export"
            )
        if scale != 1.0:
            img = np.clip(np.rint(img.astype(np.float64) * scale), 0, 65535).astype(np.uint16)
        elif img.dtype != np.uint16:
            warnings.append(f"{png.name}: depth dtype {img.dtype} -> uint16")
            img = img.astype(np.uint16)
        Image.fromarray(img).save(out / png.name)
        frames.add(png.stem)
    if not frames:
        raise BundleBuildError(f"no depth PNGs in {src}")
    return frames


def _write_confidence(src: Path, out: Path, frames: set[str], warnings: list[str]) -> None:
    """Copy confidence PNGs, or synthesise all-2 (high) when the export omits them."""
    out.mkdir(parents=True, exist_ok=True)
    if src.is_dir() and any(src.glob("*.png")):
        for png in sorted(src.glob("*.png")):
            if png.stem in frames:
                shutil.copy2(png, out / png.name)
        return
    warnings.append("no confidence/ export: synthesised all-2 (treat every depth as confident)")
    high = np.full(DEPTH_SHAPE, 2, dtype=np.uint8)
    for stem in sorted(frames):
        Image.fromarray(high).save(out / f"{stem}.png")


def _capture_id(raw: Path, provided: str | None) -> str:
    cid = provided or raw.name
    if not cid:
        raise BundleBuildError("capture id is empty (pass --capture-id)")
    return cid


def build_bundle(
    raw_dir: str | Path,
    out_root: str | Path,
    *,
    capture_id: str | None = None,
    depth_units: str = "mm",
    device: str | None = None,
    ios: str | None = None,
    app: str | None = None,
    app_version: str | None = None,
    rooms_expected: int = 0,
) -> Path:
    """Normalise ``raw_dir`` into ``out_root/<capture_id>`` and validate it as I1.

    Returns the bundle path; raises :class:`BundleBuildError` (with a readable
    message) when the export is not usable. The written bundle is re-loaded with
    :func:`scan2plan.ingest.bundle.load_bundle` so a build that "succeeds" is
    guaranteed to ingest.
    """
    raw = Path(raw_dir)
    if not raw.is_dir():
        raise BundleBuildError(f"raw export dir not found: {raw}")
    warnings: list[str] = []
    out = Path(out_root) / _capture_id(raw, capture_id)

    odo = raw / "odometry.csv"
    if not odo.is_file():
        raise BundleBuildError(
            f"odometry.csv not found in {raw} (the logger export must include poses)"
        )
    rows = _read_rows(odo)
    if not rows:
        raise BundleBuildError("odometry.csv has no rows")
    k = _camera_matrix(raw)
    if k is None:
        # Derive K from the first odometry row when the export ships intrinsics inline.
        r0 = rows[0]
        if all(r0.get(c) for c in ("fx", "fy", "cx", "cy")):
            k = np.array(
                [
                    [float(r0["fx"]), 0.0, float(r0["cx"])],
                    [0.0, float(r0["fy"]), float(r0["cy"])],
                    [0.0, 0.0, 1.0],
                ]
            )
        else:
            raise BundleBuildError(
                "no camera_matrix.csv and no fx/fy/cx/cy in odometry.csv: cannot recover intrinsics"
            )

    depth_src = raw / "depth" if (raw / "depth").is_dir() else raw / "depth_m"
    if not depth_src.is_dir():
        raise BundleBuildError(f"no depth/ (or depth_m/) folder in {raw}")
    if depth_src.name == "depth_m" and depth_units == "mm":
        depth_units = "m"  # folder name states metres; the caller need not repeat it
        warnings.append("depth_m/ detected: interpreting depth as metres")
    frames = _write_depth(depth_src, out / "depth", _depth_scale(depth_units), warnings)
    _write_confidence(raw / "confidence", out / "confidence", frames, warnings)

    if (raw / "rgb.mp4").is_file():
        shutil.copy2(raw / "rgb.mp4", out / "rgb.mp4")
    else:
        warnings.append("no rgb.mp4 (fine for the LiDAR tier; required for the video tier)")
    if (raw / "imu.csv").is_file():
        shutil.copy2(raw / "imu.csv", out / "imu.csv")

    _write_odometry(rows, k, out / "odometry.csv")
    np.savetxt(out / "camera_matrix.csv", k, delimiter=",")

    meta: dict[str, object] = {"tier": "lidar", "rooms_expected": int(rooms_expected)}
    if device:
        meta["device"] = device
    if ios:
        meta["ios"] = ios
    if app:
        meta["tool"] = {"name": app, "version": app_version or ""}
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    bundle = load_bundle(out)
    missing = sorted(f for f in bundle.odometry if f"{f.frame}.png" not in bundle.depth_frames)
    if missing:
        warnings.append(f"{len(missing)} odometry frame(s) have no depth PNG (first {missing[:3]})")
    for w in warnings:
        print(f"  warn: {w}", file=sys.stderr)
    print(
        f"built {out}: {bundle.n_frames} frames, {len(bundle.depth_frames)} depth, "
        f"{len(bundle.conf_frames)} confidence, tier={bundle.tier}"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scan2plan-build-bundle",
        description="Build a conformant I1 capture bundle from a raw LiDAR-logger export.",
    )
    parser.add_argument("raw_dir", help="the raw logger export directory")
    parser.add_argument("--out", default="bundles", help="bundle dir (default: bundles)")
    parser.add_argument("--capture-id", default=None, help="id (default: raw dir name)")
    parser.add_argument("--depth-units", choices=("mm", "m"), default="mm", help="raw depth units")
    parser.add_argument("--device", default=None, help="e.g. 'iPhone 15 Pro'")
    parser.add_argument("--ios", default=None, help="e.g. 'iOS 18.1'")
    parser.add_argument("--app", default=None, help="logger app name (pinned, plan 03 P1-2)")
    parser.add_argument("--app-version", default=None, help="logger app version")
    parser.add_argument("--rooms-expected", type=int, default=0, help="rooms in the capture")
    args = parser.parse_args(argv)
    try:
        build_bundle(
            args.raw_dir,
            args.out,
            capture_id=args.capture_id,
            depth_units=args.depth_units,
            device=args.device,
            ios=args.ios,
            app=args.app,
            app_version=args.app_version,
            rooms_expected=args.rooms_expected,
        )
    except BundleBuildError as exc:
        print(f"build_bundle: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
