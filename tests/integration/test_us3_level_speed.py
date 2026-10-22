"""US3: a coarser level is faster end-to-end than a finer one (T044, slow).

Both runs share the same constant overhead (input validation, output-pyramid write); the variable
work (reading the level and sweeping it) scales with the level's voxel count, so the coarser level
must finish faster. Timing uses the best of a few repeats to damp scheduler jitter. One SAM2
predictor is built once and reused across every run in this test so checkpoint-load cost (which
would otherwise dominate and swamp the level-dependent signal) is excluded from the measurement.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from ome_zarr_masker.config import RunConfig
from ome_zarr_masker.engine.pipeline import run_masking
from ome_zarr_masker.prompts.model import Prompt, PromptSet
from ome_zarr_masker.sam2 import Sam2Backend

from ..conftest import sam2_available, write_ome_zarr

_HAVE_SAM2 = sam2_available()

pytestmark = [
    pytest.mark.slow,
    pytest.mark.real_backend,
    pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable"),
]


def _best_runtime(store, prompts, level, backend, tmp_path, tag, repeats=5):
    """Best (minimum) end-to-end runtime over ``repeats`` runs, after one untimed warmup.

    The minimum damps scheduler/subprocess jitter: the fixed-cost stages (input validation,
    output-pyramid write) do identical work for both levels, so their floor cancels and the
    level-dependent read+sweep cost drives the comparison.
    """
    cfg = RunConfig(axes=["z"], level=level)
    run_masking(store, tmp_path / f"{tag}_warmup.ome.zarr", prompts, cfg, backend=backend)
    best = float("inf")
    for i in range(repeats):
        out = tmp_path / f"{tag}_{i}.ome.zarr"
        start = time.perf_counter()
        run_masking(store, out, prompts, cfg, backend=backend)
        best = min(best, time.perf_counter() - start)
    return best


def test_coarser_level_is_faster(tmp_path):
    vol = np.zeros((32, 400, 400), np.uint8)
    vol[8:24, 120:280, 120:280] = 200
    store = write_ome_zarr(
        tmp_path / "big.ome.zarr", vol
    )  # 2 levels: (32,400,400) and (16,200,200)

    # level 0: blob centred at (200, 200) on frame 16; level 1: (100, 100) on frame 8
    fine_prompts = PromptSet(
        [Prompt(frame_index=16, point_coords=[[200.0, 200.0]], point_labels=[1])]
    )
    coarse_prompts = PromptSet(
        [Prompt(frame_index=8, point_coords=[[100.0, 100.0]], point_labels=[1])]
    )
    backend = Sam2Backend()

    fine = _best_runtime(store, fine_prompts, 0, backend, tmp_path, "fine")
    coarse = _best_runtime(store, coarse_prompts, 1, backend, tmp_path, "coarse")

    assert coarse < fine, f"coarse {coarse:.4f}s not faster than fine {fine:.4f}s"
