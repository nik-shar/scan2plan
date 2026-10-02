"""Tests for determinism helpers (plan 01 section 7, task F-5)."""

from __future__ import annotations

import random

import numpy as np
import pytest

from scan2plan.util.seed import rng, set_seed


def test_set_seed_makes_stdlib_reproducible() -> None:
    set_seed(1337)
    first = [random.random() for _ in range(3)]
    set_seed(1337)
    second = [random.random() for _ in range(3)]
    assert first == second


def test_set_seed_makes_numpy_reproducible() -> None:
    set_seed(1337)
    first = np.random.random(3)
    set_seed(1337)
    second = np.random.random(3)
    assert np.array_equal(first, second)


def test_rng_is_reproducible() -> None:
    assert np.array_equal(rng(42).random(5), rng(42).random(5))


def test_rng_differs_by_seed() -> None:
    assert not np.array_equal(rng(1).random(5), rng(2).random(5))


@pytest.mark.parametrize("seed", [0, 1337, 2**33 + 7])
def test_rng_accepts_large_and_zero_seeds(seed: int) -> None:
    assert rng(seed).random(1).shape == (1,)
