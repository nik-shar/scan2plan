"""Raw frame access for damage evidence (plan 04e).

Depth/confidence come from the I1 bundle as uint16/uint8 PNGs. RGB is decoded
from ``rgb.mp4`` with the system ``ffmpeg`` in **one pass** (every ``stride``-th
frame, scaled to the depth grid so pixels correspond 1:1). When ``ffmpeg`` or the
video is unavailable the detector honestly reports no evidence instead of
failing (the results-out policy, plan 04).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from scan2plan.util.logging import get_logger

logger = get_logger("scan2plan.damage.frames")

#: Hard cap so a malformed/long video cannot hang the pipeline.
_FFMPEG_TIMEOUT_S = 1800


def read_depth_m(path: Path, depth_scale_m: float) -> NDArray[np.float64] | None:
    """Read a depth PNG as metres (``depth_scale_m`` per raw unit); None if absent."""
    if not path.is_file():
        return None
    return np.asarray(Image.open(path)).astype(np.float64) * depth_scale_m


def read_confidence(path: Path) -> NDArray[np.uint8] | None:
    """Read a confidence PNG as uint8; None if absent."""
    if not path.is_file():
        return None
    return np.asarray(Image.open(path)).astype(np.uint8)


def ffmpeg_available() -> bool:
    """True when a system ``ffmpeg`` is on PATH."""
    return shutil.which("ffmpeg") is not None


def extract_rgb_frames(
    video: Path,
    indices: list[int],
    size_hw: tuple[int, int],
    tmp_dir: Path,
    *,
    stride: int,
) -> dict[int, NDArray[np.uint8]]:
    """Decode sampled RGB frames from ``video``, scaled to ``size_hw`` = (H, W).

    One ffmpeg pass selects every ``stride``-th frame, so output image ``k``
    (1-based) is source frame ``(k-1)*stride`` = ``indices[k-1]``. Returns a map
    ``source_index -> RGB uint8 (H, W, 3)``; missing entries are decode gaps.
    """
    if not video.is_file() or not ffmpeg_available() or not indices:
        return {}
    tmp_dir.mkdir(parents=True, exist_ok=True)
    h, w = size_hw
    pattern = str(tmp_dir / "rgb_%06d.png")
    vf = f"select='not(mod(n\\,{stride}))',scale={w}:{h}"
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        vf,
        "-vsync",
        "0",
        "-frames:v",
        str(len(indices)),
        pattern,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=_FFMPEG_TIMEOUT_S)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
        logger.warning("ffmpeg frame extraction failed: %s", exc)
        return {}
    out: dict[int, NDArray[np.uint8]] = {}
    for k, src_idx in enumerate(indices, start=1):
        p = tmp_dir / f"rgb_{k:06d}.png"
        if p.is_file():
            out[src_idx] = np.asarray(Image.open(p).convert("RGB"))
    return out
