"""Integration tests against the real seed captures (skipped in CI, where the
git-ignored depth/confidence PNGs are absent). Locally these prove ingest+recon on
the authoritative I1 data (rule R5, fixture-first).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scan2plan.config import Config
from scan2plan.ingest import ingest_capture
from scan2plan.recon.lidar import reconstruct_lidar

SEED = Path(__file__).resolve().parents[1] / "single_room" / "c00a170fe1"

pytestmark = pytest.mark.skipif(
    not (SEED / "depth").is_dir(), reason="seed capture (git-ignored) not available"
)


def test_seed_ingest_frames() -> None:
    cir = ingest_capture(SEED)
    assert cir.session.tier == "lidar"
    assert cir.session.id == "cap_c00a170fe1"
    assert len(cir.frames) == 1715
    assert all(f.pose is not None and len(f.pose) == 16 for f in cir.frames)
    assert all(f.K is not None and len(f.K) == 9 for f in cir.frames)


def test_seed_recon_is_metric() -> None:
    cir = ingest_capture(SEED)
    points, quality = reconstruct_lidar(SEED, cir.frames, Config(), stride=200, voxel_m=0.01)
    assert points.shape[0] > 100
    y = points[:, 1]
    # floor sits ~1.4 m below the camera (world Y-up); camera y ~ 0 near session start
    assert float(y.min()) < -1.0
    assert quality.coverage is not None and quality.coverage > 0.3
