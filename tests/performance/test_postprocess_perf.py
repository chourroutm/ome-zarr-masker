"""Post-processing performance at the user's run-level size (feature 011, T032: SC-006).

The DANDI 001278 STN-block overview at level 3 is 941 x 874 x 874 voxels; the feedback's clean-up
is close, fill holes, keep the largest component, then a margin. Target: under 5 minutes and under
16 GiB peak RSS on one compute node (plan.md Performance Goals). Run on a compute node (salloc).
"""

from __future__ import annotations

import resource
import time

import numpy as np
import pytest

from ome_zarr_masker.postprocess.morphology import apply_steps
from ome_zarr_masker.postprocess.steps import parse_steps, resolve_steps

SHAPE = (941, 874, 874)
BUDGET_SECONDS = 300
BUDGET_RSS_BYTES = 16 * 2**30


def _user_like_mask() -> np.ndarray:
    """A large ellipsoid with a dropout plane, interior holes and detached fragments."""
    z, y, x = (np.arange(n, dtype=np.float32) for n in SHAPE)
    mask = np.zeros(SHAPE, dtype=bool)
    cz, cy, cx = (n / 2 for n in SHAPE)
    ry2 = ((y - cy) / 380.0) ** 2
    rx2 = ((x - cx) / 380.0) ** 2
    yx = ry2[:, None] + rx2[None, :]
    for i in range(SHAPE[0]):  # plane by plane, to keep the fixture's own memory low
        mask[i] = yx + ((z[i] - cz) / 420.0) ** 2 < 1.0
    mask[470] = False  # a sweep dropout plane
    mask[300:320, 400:420, 400:420] = False  # interior holes
    mask[600:610, 300:330, 500:520] = False
    mask[5:15, 5:15, 5:15] = True  # detached fragments
    mask[930:936, 860:868, 10:20] = True
    return mask


@pytest.mark.slow
def test_users_sequence_within_budget():
    mask = _user_like_mask()
    steps = resolve_steps(
        parse_steps("close:3,fill,largest,margin:3").steps, (1.0, 1.0, 1.0), (None, None, None)
    )
    start = time.perf_counter()
    out = apply_steps(mask, steps)
    elapsed = time.perf_counter() - start
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # KiB on Linux
    print(f"\npost-processing {SHAPE}: {elapsed:.1f} s, peak RSS {peak / 2**30:.2f} GiB")

    assert out[470, 470, 437] and out[310, 410, 410]  # gap closed, hole filled
    assert not out[10, 10, 10]  # fragment dropped
    assert out.sum() > mask.sum()
    assert elapsed < BUDGET_SECONDS
    assert peak < BUDGET_RSS_BYTES
