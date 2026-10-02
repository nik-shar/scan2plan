"""Interface I2: the Canonical Intermediate Representation (CIR).

Definition mirrors ``docs/plans/04a-cir-and-json-schema.md`` section 1. Frozen at
M2 (tag ``iface-v1.0``); append-only afterwards (rule R4). Serialised to
``plan.json`` per interface I3.

Note (ADR-0003): plan 04a defines the ``Opening`` model but omits a top-level
``openings`` list; it is added here (optional, defaulted) so OUT-1 openings can
be emitted without a breaking change.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from scan2plan.cir.measure import Measurement, Tier

# Row-major serialisations (plain JSON types, no numpy across the boundary).
Vec2 = Annotated[list[float], Field(min_length=2, max_length=2)]  # [x, y]
Vec3 = Annotated[list[float], Field(min_length=3, max_length=3)]  # [x, y, z]
Mat3 = Annotated[list[float], Field(min_length=9, max_length=9)]  # 3x3 row-major
Transform4x4 = Annotated[list[float], Field(min_length=16, max_length=16)]  # 4x4 row-major
Polygon2D = list[Vec2]

SurfaceType = Literal["wall", "ceiling", "floor"]
OpeningKind = Literal["door", "window", "passage"]
ScaleSource = Literal["lidar", "mono_depth", "vio", "reference"]
DamageClass = Literal["crack", "water_stain", "mold", "spalling", "paint_peel", "rot"]

SCHEMA_VERSION = "1.0"


class Tool(BaseModel):
    """A capture or processing tool, pinned by version (disclosure, plan 09)."""

    model_config = ConfigDict(extra="forbid")
    name: str
    version: str


class ModelRef(BaseModel):
    """A disclosed pretrained model/dataset/API (plan 01 section 9)."""

    model_config = ConfigDict(extra="forbid")
    name: str
    version: str
    licence: str | None = None
    where: str | None = None


class Session(BaseModel):
    """Capture session metadata (plan 04a section 1.1)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    tier: Tier
    device: str | None = None
    ios: str | None = None
    tool: Tool | None = None
    captured_at: str | None = None
    rooms_expected: int = Field(default=0, ge=0)


class Frame(BaseModel):
    """One captured frame (plan 04a section 1.2). Pose is camera->world (I7)."""

    model_config = ConfigDict(extra="forbid")
    idx: int = Field(ge=0)
    t: float  # seconds, monotonic per capture
    rgb_ref: str
    depth_ref: str | None = None
    conf_ref: str | None = None
    pose: Transform4x4 | None = None  # T_wc, 4x4 row-major
    K: Mat3 | None = None  # 3x3 row-major


class ReconQuality(BaseModel):
    """Reconstruction quality metrics; feed measurement CI via 04f (plan 04b §6)."""

    model_config = ConfigDict(extra="forbid")
    track_len: float | None = None
    mean_reproj: float | None = None
    plane_rms: float | None = None
    coverage: float | None = None
    scale_uncertainty: float | None = None


class Recon(BaseModel):
    """Per-tier reconstruction artifact (interface I8, plan 04a section 1.3)."""

    model_config = ConfigDict(extra="forbid")
    points_ref: str | None = None
    scale: float = 1.0
    scale_source: ScaleSource = "lidar"
    pose_graph_ref: str | None = None
    quality: ReconQuality = Field(default_factory=ReconQuality)


class Plane(BaseModel):
    """A plane as (unit normal, offset d) with normal . p + d = 0."""

    model_config = ConfigDict(extra="forbid")
    normal: Vec3
    d: float


class Room(BaseModel):
    """A room (plan 04a section 1.4); boundary is the floor polygon (room frame)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    name: str | None = None
    boundary: Polygon2D = Field(default_factory=list)
    ceiling_height: Measurement | None = None
    floor_area: Measurement | None = None


class Surface(BaseModel):
    """A wall/ceiling/floor surface (plan 04a section 1.4)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    room_id: str
    type: SurfaceType
    plane: Plane | None = None
    polygon: Polygon2D = Field(default_factory=list)


class Opening(BaseModel):
    """A door/window/passage opening (plan 04a section 1.4 + ADR-0003)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    room_id: str
    surface_id: str
    kind: OpeningKind
    width: Measurement | None = None
    height: Measurement | None = None
    detection_confidence: float | None = None


class SE2(BaseModel):
    """A planar rigid transform (x, y, theta) in the stitched plan frame."""

    model_config = ConfigDict(extra="forbid")
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0  # radians


class Footprint(BaseModel):
    """A stitched footprint measurement for the drift ablation (G-DRIFT)."""

    model_config = ConfigDict(extra="forbid")
    footprint_m2: float = Field(ge=0.0)
    closure_gap_m: float | None = Field(default=None, ge=0.0)


class StitchEdge(BaseModel):
    """A relative constraint between two rooms (plan 04d)."""

    model_config = ConfigDict(extra="forbid")
    room_a: str
    room_b: str
    transform: SE2 = Field(default_factory=SE2)
    kind: str = "connector"  # connector | loop_closure
    weight: float | None = None


class LoopClosure(BaseModel):
    """A detected revisit constraint (plan 04d)."""

    model_config = ConfigDict(extra="forbid")
    rooms: list[str] = Field(default_factory=list)
    gap_m: float | None = Field(default=None, ge=0.0)
    evidence_ref: str | None = None


class Ablation(BaseModel):
    """Drift on/off footprints emitted from the same code path (G-DRIFT ablation)."""

    model_config = ConfigDict(extra="forbid")
    loop_closure_on: Footprint | None = None
    off: Footprint | None = None


class Stitch(BaseModel):
    """Multi-room stitch result (interface produced by 04d)."""

    model_config = ConfigDict(extra="forbid")
    plan_frame: str = "stitched_world_xy"
    room_transforms: dict[str, SE2] = Field(default_factory=dict)
    edges: list[StitchEdge] = Field(default_factory=list)
    closures: list[LoopClosure] = Field(default_factory=list)
    overlap_ok: bool | None = None
    unstitched: bool | None = None  # must be False for multi-room captures (I3 rule 4)
    ablation: Ablation | None = None


class Extent(BaseModel):
    """Metric extent of a damage region (plan 04e)."""

    model_config = ConfigDict(extra="forbid")
    area_m2: float | None = Field(default=None, ge=0.0)
    bbox_m: list[float] | None = None


class Damage(BaseModel):
    """A damage region on a surface (plan 04a section 1.6 / 04e)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    surface_id: str
    cls: DamageClass
    polygon: Polygon2D = Field(default_factory=list)
    extent: Extent = Field(default_factory=Extent)
    evidence_ref: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ConcealedFlag(BaseModel):
    """A concealed-damage flag carrying the rule id that fired (OUT-4)."""

    model_config = ConfigDict(extra="forbid")
    surface_id: str
    rule_id: str
    rule_text: str | None = None
    inputs: dict[str, float] = Field(default_factory=dict)
    evidence_ref: str | None = None


class ScopeItem(BaseModel):
    """A repair line item keyed to a surface (OUT-5)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    surface_id: str
    task: str
    quantity: Measurement | None = None


class Provenance(BaseModel):
    """Provenance block required by I3 (rule 5): tier, tool, models, git sha, seed."""

    model_config = ConfigDict(extra="forbid")
    tier: Tier
    tool: Tool | None = None
    device: str | None = None
    git_sha: str | None = None
    code_version: str | None = None
    seed: int = 1337
    models: list[ModelRef] = Field(default_factory=list)
    schema_version: str = SCHEMA_VERSION


class CIR(BaseModel):
    """Top-level Canonical Intermediate Representation (I2)."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION
    session: Session
    frames: list[Frame] = Field(default_factory=list)
    recon: Recon | None = None
    rooms: list[Room] = Field(default_factory=list)
    surfaces: list[Surface] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)  # ADR-0003
    stitch: Stitch | None = None
    damages: list[Damage] = Field(default_factory=list)
    concealed: list[ConcealedFlag] = Field(default_factory=list)
    scope: list[ScopeItem] = Field(default_factory=list)
    measures: list[Measurement] = Field(default_factory=list)
    provenance: Provenance
