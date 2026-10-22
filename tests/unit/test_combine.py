"""Unit tests for consensus combination (T008)."""

from __future__ import annotations

import numpy as np
import pytest

from ome_zarr_masker.engine.combine import VoteAccumulator, combine_votes


def test_majority_vote():
    votes = np.array([0, 1, 2, 3])
    # 3 sweeps -> majority is > 1.5
    assert combine_votes(votes, 3, "majority").tolist() == [False, False, True, True]


def test_majority_tie_resolves_to_background():
    votes = np.array([1, 2])
    # 2 sweeps -> tie at 1 (== n/2) is background
    assert combine_votes(votes, 2, "majority").tolist() == [False, True]


def test_union_and_intersection():
    votes = np.array([0, 1, 2])
    assert combine_votes(votes, 2, "union").tolist() == [False, True, True]
    assert combine_votes(votes, 2, "intersection").tolist() == [False, False, True]


def test_unknown_rule_raises():
    with pytest.raises(ValueError):
        combine_votes(np.array([1]), 1, "bogus")


def test_accumulator_majority(tmp_path):
    acc = VoteAccumulator((4,), tmp_path)
    acc.add(np.array([1, 1, 0, 0], bool))
    acc.add(np.array([1, 0, 1, 0], bool))
    acc.add(np.array([1, 0, 0, 0], bool))
    assert acc.n_sweeps == 3
    assert acc.result("majority").tolist() == [True, False, False, False]
