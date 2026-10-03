#!/usr/bin/env python3
"""Capture QA: check an I1 bundle (or a raw export) before leaving the room (plan 03 P1-5).

    python scripts/check_bundle.py <capture_dir> [--sample N]

Reports frames, depth/confidence coverage, depth range, and camera travel, and warns
when a capture is likely to produce a weak plan (low depth coverage, tiny travel,
missing confidence, implausible depth range). Exit 0 when the bundle ingests, 1 when it
cannot be read at all.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from scan2plan.ingest.bundle import DEPTH_SHAPE, BundleError, load_bundle

#: Plausible handheld depth range for a room scan (metres).
RANGE_M = (0.2, 12.0)
#: Below this mean depth coverage the capture is probably too thin.
MIN_COVERAGE = 0.30


def _camera_travel(rows) -> float:
    pts = np.array([[r.position[0], r.position[2]] for r in rows], dtype=np.float64)
    if pts.shape[0] < 2:
        return 0.0
    return float(np.hypot(*np.diff(pts, axis=0).T).sum())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_dir")
    parser.add_argument("--sample", type=int, default=20, help="frames to sample for coverage")
    args = parser.parse_args(argv)
    cap = Path(args.capture_dir)
    try:
        bundle = load_bundle(cap)
    except BundleError as exc:
        print(f"INVALID bundle: {exc}", file=sys.stderr)
        return 1

    warnings: list[str] = []
    stride = max(1, bundle.n_frames // max(1, args.sample))
    cov: list[float] = []
    lo, hi = np.inf, 0.0
    for row in bundle.odometry[::stride]:
        name = f"{row.frame}.png"
        if name not in bundle.depth_frames:
            continue
        depth = np.asarray(Image.open(cap / "depth" / name)).astype(np.float64)
        if depth.shape != DEPTH_SHAPE:
            warnings.append(f"{name}: depth {depth.shape[1]}x{depth.shape[0]} != 256x192")
        cov.append(float(np.mean(depth > 0)))
        pos = depth[depth > 0]
        if pos.size:
            lo, hi = min(lo, float(pos.min())), max(hi, float(pos.max()))

    print(f"capture      : {bundle.capture_id}  (tier {bundle.tier})")
    print(
        f"frames       : {bundle.n_frames} odometry, {len(bundle.depth_frames)} depth, "
        f"{len(bundle.conf_frames)} confidence"
    )
    print(f"camera travel: {_camera_travel(bundle.odometry):.1f} m")
    if cov:
        print(f"depth coverage (mean over {len(cov)} sampled frames): {np.mean(cov):.0%}")
        print(f"depth range  : {lo / 1000:.2f} - {hi / 1000:.2f} m (uint16 mm)")
    else:
        warnings.append("no sampled frame had depth")

    if not bundle.conf_frames:
        warnings.append("no confidence/ PNGs (depth confidence gate cannot fire)")
    if cov and float(np.mean(cov)) < MIN_COVERAGE:
        warnings.append(
            f"low depth coverage {np.mean(cov):.0%} (< {MIN_COVERAGE:.0%}): move slower / add light"
        )
    if cov and not (RANGE_M[0] <= hi / 1000 <= RANGE_M[1]):
        warnings.append(f"max depth {hi / 1000:.2f} m outside {RANGE_M}: check depth units (mm?)")
    if _camera_travel(bundle.odometry) < 1.0:
        warnings.append("camera travel < 1 m: did the scan actually move?")
    if bundle.n_frames < 30:
        warnings.append(f"only {bundle.n_frames} frames: scan longer for wall support")

    for w in warnings:
        print(f"  warn: {w}")
    print("VERDICT:", "OK" if not warnings else f"{len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
