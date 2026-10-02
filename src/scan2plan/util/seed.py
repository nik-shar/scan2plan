"""Determinism helpers - every stochastic step derives its RNG from here."""

from __future__ import annotations

import random

import numpy as np
from numpy.random import Generator

_UINT32 = 2**32


def set_seed(seed: int) -> None:
    """Seed the global ``random`` and ``numpy`` RNGs (task F-5)."""
    random.seed(seed)
    np.random.seed(seed % _UINT32)


def rng(seed: int) -> Generator:
    """Return an independent, reproducible numpy Generator."""
    return np.random.default_rng(seed % _UINT32)
