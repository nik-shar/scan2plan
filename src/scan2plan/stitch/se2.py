"""SE(2) rigid-transform math for the stitched plan frame (plan 04d section 2.4).

All transforms are plan-view ``SE2`` values (interface I2): ``(x, y, theta)`` with
``theta`` in radians (I7). A transform ``T_ab`` maps points from frame ``a`` into
frame ``b``: ``p_b = R(theta) @ p_a + t``.
"""

from __future__ import annotations

import math

from scan2plan.cir import SE2

_TAU = 2.0 * math.pi


def wrap_angle(theta: float) -> float:
    """Wrap an angle to [-pi, pi)."""
    return (theta + math.pi) % _TAU - math.pi


def identity() -> SE2:
    """The identity transform."""
    return SE2(x=0.0, y=0.0, theta=0.0)


def compose(a: SE2, b: SE2) -> SE2:
    """Return ``a . b`` (apply ``b`` first, then ``a``)."""
    c, s = math.cos(a.theta), math.sin(a.theta)
    return SE2(
        x=a.x + c * b.x - s * b.y,
        y=a.y + s * b.x + c * b.y,
        theta=wrap_angle(a.theta + b.theta),
    )


def inverse(a: SE2) -> SE2:
    """Return ``a^-1``."""
    c, s = math.cos(a.theta), math.sin(a.theta)
    return SE2(x=-(c * a.x + s * a.y), y=-(-s * a.x + c * a.y), theta=wrap_angle(-a.theta))


def relative(a: SE2, b: SE2) -> SE2:
    """Return ``a^-1 . b``: frame ``b`` expressed in frame ``a``."""
    return compose(inverse(a), b)


def apply(t: SE2, px: float, py: float) -> tuple[float, float]:
    """Transform a plan-frame point by ``t``."""
    c, s = math.cos(t.theta), math.sin(t.theta)
    return (c * px - s * py + t.x, s * px + c * py + t.y)


def translation_norm(t: SE2) -> float:
    """Translation magnitude (metres)."""
    return math.hypot(t.x, t.y)
