"""Stage S1: ingest an I1 bundle into the CIR (``session`` + ``frames``).

Per plan 04 section 2 the ingest output is the CIR ``session`` and ``frames[]``.
Everything from S3 onward is tier-agnostic; only S1/S2 read the raw bundle.
"""

from __future__ import annotations

from pathlib import Path

from scan2plan.cir import CIR, Frame, Session, Tool
from scan2plan.config import Config
from scan2plan.ingest.bundle import CaptureBundle, OdometryRow, load_bundle
from scan2plan.util.frames import pose_from_xyz_quat
from scan2plan.util.provenance import build_provenance

__all__ = ["CaptureBundle", "ingest_capture", "load_bundle"]


def _frame_from_row(row: OdometryRow, bundle: CaptureBundle) -> Frame:
    pose = pose_from_xyz_quat(*row.position, *row.quaternion)  # T_wc, 4x4
    depth_file = f"{row.frame}.png"
    return Frame(
        idx=int(row.frame),
        t=row.timestamp,
        rgb_ref=bundle.rgb_ref,
        depth_ref=f"depth/{depth_file}" if depth_file in bundle.depth_frames else None,
        conf_ref=f"confidence/{depth_file}" if depth_file in bundle.conf_frames else None,
        pose=[float(v) for v in pose.flatten()],  # row-major 4x4
        K=[float(row.fx), 0.0, float(row.cx), 0.0, float(row.fy), float(row.cy), 0.0, 0.0, 1.0],
    )


def build_session(bundle: CaptureBundle) -> Session:
    """Build the CIR session from bundle metadata (I1 / plan 04a section 1.1)."""
    meta = bundle.meta
    tool = None
    raw_tool = meta.get("tool")
    if isinstance(raw_tool, dict):
        tool = Tool(
            name=str(raw_tool.get("name", "unknown")), version=str(raw_tool.get("version", ""))
        )
    return Session(
        id=f"cap_{bundle.capture_id}",
        tier=bundle.tier,
        device=meta.get("device"),
        ios=meta.get("ios"),
        tool=tool,
        captured_at=meta.get("captured_at"),
        rooms_expected=int(meta.get("rooms_expected", 0) or 0),
    )


def ingest_capture(capture_dir: str | Path, config: Config | None = None) -> CIR:
    """Parse a bundle and return a CIR with ``session`` + ``frames`` + provenance."""
    bundle = load_bundle(capture_dir)
    cfg = config or Config()
    frames = [_frame_from_row(row, bundle) for row in bundle.odometry]
    return CIR(
        session=build_session(bundle),
        frames=frames,
        provenance=build_provenance(bundle.tier, cfg, bundle.meta),
    )
