"""Interface I6: Measurement + uncertainty type (owned by plan 04f).

Definition mirrors ``docs/plans/04f-uncertainty-and-calibration.md`` section 1.
Every quantity that crosses a module boundary is a ``Measurement``; bare floats
are not allowed. Append-only (rule R4): new fields are optional and defaulted.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The three mandatory input tiers (Part 1 of the brief).
Tier = Literal["photos", "video", "lidar"]

#: Nominal coverage of a confidence interval unless a measurement states otherwise.
NOMINAL_COVERAGE = 0.90


class Measurement(BaseModel):
    """A scalar quantity with a calibrated confidence interval.

    Invariant (enforced): ``ci_low <= value <= ci_high``; nominal coverage is
    90% unless ``nominal`` says otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    ci_low: float
    ci_high: float
    method: str = Field(min_length=1)  # e.g. plane_fit | sfm | lidar | rule | mono_depth
    tier: Tier
    sources: list[str] = Field(default_factory=list)
    nominal: float = Field(default=NOMINAL_COVERAGE, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_interval(self) -> Self:
        """Enforce ``ci_low <= value <= ci_high`` (no confident garbage)."""
        if self.ci_low > self.ci_high:
            raise ValueError(f"ci_low ({self.ci_low}) must be <= ci_high ({self.ci_high})")
        if not (self.ci_low <= self.value <= self.ci_high):
            raise ValueError(
                f"value ({self.value}) outside interval [{self.ci_low}, {self.ci_high}]"
            )
        return self

    @property
    def half_width(self) -> float:
        """Half-width of the interval (used by 04f calibration bucketing)."""
        return (self.ci_high - self.ci_low) / 2.0
