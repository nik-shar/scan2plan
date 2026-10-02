#!/usr/bin/env python3
"""Task B-0 (plan 04b section 2): verify the seed depth-unit hypothesis.

Claim under test: ``depth/*.png`` are uint16 **millimetres**, i.e. scale
``0.001`` m/unit (config ``depth_scale_m``, interface I4).

Method (no tape measure is available for the seed captures):
  1. Back-project sampled depth frames with the ``odometry.csv`` poses into the
     gravity-aligned world frame (Y up, per interface I7).
  2. Extract the dominant horizontal planes from the world-Y histogram: a correct
     scale *and* a correct back-projection convention yield sharp, physically
     plausible planes.
  3. Report camera height above the floor and floor-to-ceiling height; a handheld
     room scan must land at ~1.2-1.6 m and ~2.3-2.8 m. Repeat at other assumed
     scales to show that only millimetres is plausible.

Usage:
    python scripts/verify_depth_units.py [capture_dir ...] [--stride N] [--json PATH]

Exit code 0 if the millimetre hypothesis is confirmed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from scan2plan.util.frames import quat_xyzw_to_matrix

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURES = [
    "single_room/c00a170fe1",
    "single_scan_floor_only/1a8384c3f6",
    "single_scan_with_ceiling/c7d28f72c6",
]
# Plausible handheld ranges used for the verdict.
CAMERA_HEIGHT_RANGE_M = (1.0, 2.0)
ROOM_HEIGHT_RANGE_M = (2.0, 3.2)
# A second horizontal plane is only a ceiling if it sits a room-height above the
# floor; a ~1.2 m plane is furniture (counter/table), not a ceiling.
MIN_CEILING_ABOVE_FLOOR_M = 1.8
ALT_SCALES = (0.0005, 0.001, 0.002, 0.01)


@dataclass
class PlaneFit:
    """A horizontal plane detected in the world frame."""

    height_m: float
    support: float  # fraction of all points within +/-2 cm of the plane
    rms_m: float  # RMS world-Y residual of points within +/-3 cm


@dataclass
class B0Result:
    capture: str
    n_frames_sampled: int
    scale_m_per_unit: float
    floor: PlaneFit
    ceiling: PlaneFit | None
    camera_height_m: float
    room_height_m: float | None
    footprint_m2: float
    camera_travel_m: float
    plausible: bool


def _load_odometry(path: Path) -> list[dict[str, str]]:
    with path.open() as fh:
        return [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def _load_camera_matrix(path: Path) -> np.ndarray:
    return np.loadtxt(path, delimiter=",", dtype=np.float64)


def reconstruct(
    capture: Path, *, scale: float, stride: int, min_conf: int
) -> tuple[np.ndarray, np.ndarray]:
    """Return (world_points, camera_positions) for sampled frames.

    Uses the pinhole back-projection ``X=(u-cx)d/fx, Y=(v-cy)d/fy, Z=d`` which
    the empirical check (ADR-0002) shows is the odometry-consistent convention.
    """
    rows = _load_odometry(capture / "odometry.csv")
    k = _load_camera_matrix(capture / "camera_matrix.csv")
    # K applies to 1920x1440; depth/confidence are 256x192.
    sx, sy = 256 / 1920, 192 / 1440
    fx, fy, cx, cy = k[0, 0] * sx, k[1, 1] * sy, k[0, 2] * sx, k[1, 2] * sy

    points: list[np.ndarray] = []
    cams: list[np.ndarray] = []
    for row in rows[::stride]:
        idx = row["frame"]
        depth = np.asarray(Image.open(capture / "depth" / f"{idx}.png")).astype(np.float64) * scale
        conf = np.asarray(Image.open(capture / "confidence" / f"{idx}.png")).astype(np.uint8)
        mask = (depth > 0.0) & (conf >= min_conf)
        ys, xs = np.nonzero(mask)
        d = depth[ys, xs]
        cam = np.column_stack([(xs - cx) * d / fx, (ys - cy) * d / fy, d])
        rot = quat_xyzw_to_matrix(*(float(row[k2]) for k2 in ("qx", "qy", "qz", "qw")))
        t = np.array([float(row[k2]) for k2 in ("x", "y", "z")], dtype=np.float64)
        points.append((rot @ cam.T).T + t)
        cams.append(t)
    return np.vstack(points), np.vstack(cams)


def _detect_planes(y: np.ndarray, *, bin_w: float = 0.01, min_sep: float = 1.0) -> list[PlaneFit]:
    """Find up to two dominant horizontal planes, sorted low->high by height."""
    edges = np.arange(float(y.min()), float(y.max()) + bin_w, bin_w)
    hist, edges = np.histogram(y, bins=edges)
    centers = (edges[:-1] + edges[1:]) / 2
    smooth = np.convolve(hist, np.ones(5) / 5, mode="same")
    candidates = [
        i for i in range(1, len(smooth) - 1) if smooth[i] >= smooth[i - 1] and smooth[i] >= smooth[i + 1]
    ]
    candidates.sort(key=lambda i: smooth[i], reverse=True)

    picked: list[int] = []
    for i in candidates:
        if all(abs(centers[i] - centers[j]) >= min_sep for j in picked):
            picked.append(i)
        if len(picked) == 2:
            break

    fits: list[PlaneFit] = []
    for i in sorted(picked):
        h = float(centers[i])
        near = y[np.abs(y - h) <= 0.03]
        fits.append(
            PlaneFit(
                height_m=round(h, 3),
                support=round(float(np.mean(np.abs(y - h) <= 0.02)), 4),
                rms_m=round(float(np.std(near)) if near.size else float("nan"), 4),
            )
        )
    return fits


def analyse(capture: Path, *, scale: float, stride: int, min_conf: int) -> B0Result:
    points, cams = reconstruct(capture, scale=scale, stride=stride, min_conf=min_conf)
    planes = _detect_planes(points[:, 1])
    floor = planes[0]
    ceiling = None
    if len(planes) > 1 and (planes[1].height_m - floor.height_m) >= MIN_CEILING_ABOVE_FLOOR_M:
        ceiling = planes[1]
    camera_height = float(np.median(cams[:, 1])) - floor.height_m
    room_height = (ceiling.height_m - floor.height_m) if ceiling else None

    # Footprint from the floor slab (points within +/-5 cm of the floor plane).
    slab = points[np.abs(points[:, 1] - floor.height_m) <= 0.05]
    extent_x = float(np.ptp(slab[:, 0])) if slab.size else 0.0
    extent_z = float(np.ptp(slab[:, 2])) if slab.size else 0.0
    travel = float(np.linalg.norm(np.ptp(cams, axis=0)))

    plausible = (
        CAMERA_HEIGHT_RANGE_M[0] <= camera_height <= CAMERA_HEIGHT_RANGE_M[1]
        and (room_height is None or ROOM_HEIGHT_RANGE_M[0] <= room_height <= ROOM_HEIGHT_RANGE_M[1])
    )
    rel = capture.relative_to(REPO_ROOT) if capture.is_absolute() else capture
    n_rows = len(_load_odometry(capture / "odometry.csv"))
    return B0Result(
        capture=str(rel),
        n_frames_sampled=len(range(0, n_rows, stride)),
        scale_m_per_unit=scale,
        floor=floor,
        ceiling=ceiling,
        camera_height_m=round(camera_height, 3),
        room_height_m=round(room_height, 3) if room_height is not None else None,
        footprint_m2=round(extent_x * extent_z, 2),
        camera_travel_m=round(travel, 2),
        plausible=bool(plausible),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("captures", nargs="*", default=DEFAULT_CAPTURES)
    parser.add_argument("--stride", type=int, default=100, help="sample every Nth frame (default 100)")
    parser.add_argument(
        "--min-confidence", type=int, default=1, help="min ARKit confidence to keep (default 1)"
    )
    parser.add_argument("--json", type=Path, default=None, help="write the result report here")
    args = parser.parse_args(argv)

    results = [
        analyse(REPO_ROOT / c, scale=0.001, stride=args.stride, min_conf=args.min_confidence)
        for c in args.captures
    ]

    print("== B-0 depth-unit verification (assumed scale 0.001 m/unit == millimetres) ==")
    for r in results:
        print(
            f"\n[{r.capture}]  frames_sampled={r.n_frames_sampled}"
            f"\n  floor    y={r.floor.height_m:+.3f} m  support={r.floor.support:.2%}  "
            f"rms={r.floor.rms_m * 100:.2f} cm"
        )
        if r.ceiling:
            print(
                f"  ceiling  y={r.ceiling.height_m:+.3f} m  support={r.ceiling.support:.2%}  "
                f"rms={r.ceiling.rms_m * 100:.2f} cm"
            )
        print(
            f"  camera height={r.camera_height_m:.3f} m  room height={r.room_height_m}  "
            f"footprint~{r.footprint_m2} m2  camera travel={r.camera_travel_m} m  -> "
            f"{'plausible' if r.plausible else 'IMPLAUSIBLE'}"
        )

    # Scale-discrimination table on the first capture: only mm is plausible.
    first = REPO_ROOT / args.captures[0]
    labels = {"0.0005": "0.5 mm (2x too small)", "0.001": "1 mm (hypothesis)",
              "0.002": "2 mm (2x too big)", "0.01": "10 mm (10x too big)"}
    print(f"\n-- scale discrimination on {args.captures[0]} (camera height vs assumed scale) --")
    for s in ALT_SCALES:
        res = analyse(first, scale=s, stride=max(args.stride, 200), min_conf=args.min_confidence)
        print(
            f"  scale={s:<7} {labels[str(s)]:<20} -> camera height={res.camera_height_m:+.3f} m  "
            f"{'PLAUSIBLE' if res.plausible else 'implausible'}"
        )

    confirmed = all(r.plausible for r in results)
    verdict = "CONFIRMED" if confirmed else "NOT CONFIRMED"
    print(f"\nVERDICT: depth units = millimetres (scale 0.001 m/unit) -> {verdict}")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")
        print(f"wrote {args.json}")

    return 0 if confirmed else 1


if __name__ == "__main__":
    sys.exit(main())