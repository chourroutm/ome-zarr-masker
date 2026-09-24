"""Performance benchmark for frame_range preview modes (feature 007, SC-001/SC-002, C-PV-13/14).

Mirrors test_benchmark.py's pattern: one Sam2Backend built once and reused across runs so
checkpoint-load cost doesn't swamp the signal being measured.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from organ_masker_lite.config import RunConfig
from organ_masker_lite.engine.pipeline import compute_mask
from organ_masker_lite.prompts.model import Prompt, PromptSet
from organ_masker_lite.sam2 import Sam2Backend

from ..conftest import sam2_available, write_ome_zarr

_HAVE_SAM2 = sam2_available()

pytestmark = [
    pytest.mark.slow,
    pytest.mark.real_backend,
    pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable"),
]

SINGLE_SLICE_BUDGET_S = 10.0


def _blob_store(tmp_path, depth, hw=192, n_levels=1):
    vol = np.zeros((depth, hw, hw), np.uint8)
    vol[depth // 4 : depth * 3 // 4, hw // 4 : hw * 3 // 4, hw // 4 : hw * 3 // 4] = 200
    return write_ome_zarr(tmp_path / f"d{depth}.ome.zarr", vol, n_levels=n_levels)


def _center_prompt(frame, hw=192):
    return PromptSet(
        [Prompt(frame_index=frame, point_coords=[[hw // 2, hw // 2]], point_labels=[1])]
    )


def test_single_slice_completes_under_budget(tmp_path):
    depth = 64
    store = _blob_store(tmp_path, depth)
    frame = depth // 2
    backend = Sam2Backend()

    cfg = RunConfig(axes=["z"], frame_range=(frame, frame))
    # warm-up run: pay checkpoint/JIT cost once, outside the timed measurement
    compute_mask(store, _center_prompt(frame), cfg, backend=backend)

    start = time.perf_counter()
    compute_mask(store, _center_prompt(frame), cfg, backend=backend)
    elapsed = time.perf_counter() - start

    assert elapsed < SINGLE_SLICE_BUDGET_S, (
        f"single-slice took {elapsed:.2f}s, budget {SINGLE_SLICE_BUDGET_S}s"
    )


def test_few_slices_window_cost_independent_of_volume_depth(tmp_path):
    shallow, deep = 32, 256
    half_width = 5
    backend = Sam2Backend()

    def best_window_time(depth):
        store = _blob_store(tmp_path, depth)
        frame = depth // 2
        cfg = RunConfig(axes=["z"], frame_range=(frame - half_width, frame + half_width))
        prompts = _center_prompt(frame)
        compute_mask(store, prompts, cfg, backend=backend)  # warm-up
        best_t = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            compute_mask(store, prompts, cfg, backend=backend)
            best_t = min(best_t, time.perf_counter() - start)
        return best_t

    shallow_t = best_window_time(shallow)
    deep_t = best_window_time(deep)

    # same fixed window size regardless of total volume depth -> comparable cost, generous
    # multiplicative tolerance since wall-clock timing on shared hardware is noisier than RAM
    assert deep_t < shallow_t * 3, (
        f"few-slices cost scaled with depth: shallow(depth={shallow})={shallow_t:.2f}s, "
        f"deep(depth={deep})={deep_t:.2f}s"
    )
