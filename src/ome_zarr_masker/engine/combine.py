"""Per-voxel consensus combination of per-sweep masks via an on-disk vote accumulator."""

from __future__ import annotations

from pathlib import Path

import numpy as np

VALID_RULES = ("majority", "union", "intersection")


def combine_votes(votes: np.ndarray, n_sweeps: int, rule: str = "majority") -> np.ndarray:
    """Reduce a vote-count array to a binary mask.

    - ``majority``: foreground where more than half the sweeps agree (ties -> background).
    - ``union``: foreground where any sweep agrees.
    - ``intersection``: foreground where all sweeps agree.
    """
    votes = np.asarray(votes)
    if rule == "majority":
        return votes > (n_sweeps / 2)
    if rule == "union":
        return votes >= 1
    if rule == "intersection":
        return votes == n_sweeps if n_sweeps > 0 else np.zeros_like(votes, dtype=bool)
    raise ValueError(f"unknown combine rule '{rule}'; valid: {', '.join(VALID_RULES)}")


class VoteAccumulator:
    """Accumulates per-sweep foreground votes in an on-disk memmap (depth-independent RAM)."""

    def __init__(self, shape: tuple[int, ...], workdir: str | Path):
        self.path = Path(workdir) / "votes.dat"
        self.votes = np.memmap(self.path, dtype=np.uint16, mode="w+", shape=tuple(shape))
        self.votes[...] = 0
        self.n_sweeps = 0

    def add(self, mask: np.ndarray) -> None:
        self.votes[np.asarray(mask, dtype=bool)] += 1
        self.n_sweeps += 1

    def result(self, rule: str = "majority") -> np.ndarray:
        return combine_votes(np.asarray(self.votes), self.n_sweeps, rule)
