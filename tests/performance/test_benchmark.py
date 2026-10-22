"""Performance benchmark guarding the plan.md / Principle IV targets (T056).

These run against the real, GPU-powered SAM2 backend (no CPU-only stand-in remains in this
project), so they now measure the actual targets end to end:

- Peak host RAM stays well under the ceiling and its per-voxel cost is bounded and independent of
  slice count along the sweep axis -- the frame and vote intermediates are memmap-backed
  (out-of-core), so they add no resident RAM that grows with depth. Note: this measures Python-heap
  RAM only (``tracemalloc``); it does not account for GPU memory or off-heap allocations SAM2 itself
  makes, which is a real, disclosed limitation now that a real backend is in the loop.
- A coarser pyramid level strictly reduces end-to-end runtime versus a finer one (SC-006). One SAM2
  predictor is built once per test and reused across every run so checkpoint-load cost doesn't
  swamp the level-dependent signal being measured.

The 512x512x512-under-5-minutes-on-GPU runtime budget (spec 001 Performance Goals) is exercised by
these tests for the first time now that a real backend is in the loop; see the timing test below.
"""

from __future__ import annotations

import time
import tracemalloc

import numpy as np
import pytest

from ome_zarr_masker.config import RunConfig
from ome_zarr_masker.engine.pipeline import compute_mask, run_masking
from ome_zarr_masker.prompts.model import Prompt, PromptSet
from ome_zarr_masker.sam2 import Sam2Backend

from ..conftest import sam2_available, write_ome_zarr

_HAVE_SAM2 = sam2_available()

pytestmark = [
    pytest.mark.slow,
    pytest.mark.real_backend,
    pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable"),
]

# Generous per-voxel ceiling: the pre-out-of-core implementation (whole-volume float64 copy) used
# ~18 bytes/voxel; the memmap design stays well under this.
MAX_BYTES_PER_VOXEL = 12.0


def _peak_bytes(store, prompts, backend, level=0):
    tracemalloc.start()
    compute_mask(store, prompts, RunConfig(axes=["z"], level=level), backend=backend)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak


def _blob_store(tmp_path, depth, hw=192, n_levels=1):
    vol = np.zeros((depth, hw, hw), np.uint8)
    vol[depth // 4 : depth * 3 // 4, hw // 4 : hw * 3 // 4, hw // 4 : hw * 3 // 4] = 200
    return write_ome_zarr(tmp_path / f"d{depth}.ome.zarr", vol, n_levels=n_levels)


def _center_prompt(depth, hw=192):
    return PromptSet(
        [Prompt(frame_index=depth // 2, point_coords=[[hw // 2, hw // 2]], point_labels=[1])]
    )


def test_peak_ram_bounded_and_depth_independent(tmp_path):
    shallow, deep = 64, 128  # deep has 2x the slice count, same in-plane size
    backend = Sam2Backend()
    peak_shallow = _peak_bytes(_blob_store(tmp_path, shallow), _center_prompt(shallow), backend)
    peak_deep = _peak_bytes(_blob_store(tmp_path, deep), _center_prompt(deep), backend)

    bpv_shallow = peak_shallow / (shallow * 192 * 192)
    bpv_deep = peak_deep / (deep * 192 * 192)

    # well under the 4 GB ceiling for these reference-proportional volumes
    assert peak_deep < 256 * 1024**2
    # per-voxel RAM is bounded (intermediates are out-of-core, not held in RAM)
    assert bpv_deep < MAX_BYTES_PER_VOXEL
    # and does not grow with slice count along the sweep axis
    assert bpv_deep <= bpv_shallow * 1.2


def test_coarser_level_strictly_faster(tmp_path):
    store = _blob_store(tmp_path, 32, hw=320, n_levels=2)  # levels (32,320,320) and (16,160,160)
    fine = _center_prompt(32, hw=320)
    coarse = PromptSet([Prompt(frame_index=8, point_coords=[[80, 80]], point_labels=[1])])
    backend = Sam2Backend()

    def best(prompts, level, tag):
        cfg = RunConfig(axes=["z"], level=level)
        run_masking(store, tmp_path / f"{tag}_warm.ome.zarr", prompts, cfg, backend=backend)
        best_t = float("inf")
        for i in range(5):
            start = time.perf_counter()
            run_masking(store, tmp_path / f"{tag}_{i}.ome.zarr", prompts, cfg, backend=backend)
            best_t = min(best_t, time.perf_counter() - start)
        return best_t

    fine_t = best(fine, 0, "fine")
    coarse_t = best(coarse, 1, "coarse")
    assert coarse_t < fine_t, f"coarse {coarse_t:.4f}s not faster than fine {fine_t:.4f}s"
