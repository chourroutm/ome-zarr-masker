"""Performance budgets for the scalable mask writer (feature 009, SC-001, SC-005).

Memory is measured with ``tracemalloc`` around ``write_mask`` against a scaled-down write budget.
Time is measured relative to ``_legacy_write`` -- the pre-feature algorithm (whole-level resize, one
uncompressed chunk per level) kept here as a reference and timed in the same process, so the budget
doesn't depend on which machine runs the suite.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import zarr

from organ_masker_lite.io.reader import OmeZarrReader

from ..conftest import write_ome_zarr
from ..unit.test_writer import _reference_nn_resize


def _reference_fixture(tmp_path: Path) -> tuple[OmeZarrReader, np.ndarray]:
    """3-level input, finest 64x512x512, and a run-level (level 1) mask with one cuboid."""
    vol = np.zeros((64, 512, 512), np.uint8)
    reader = OmeZarrReader(write_ome_zarr(tmp_path / "ref_in.ome.zarr", vol, n_levels=3))
    mask = np.zeros(reader.level_shape(1), np.uint8)
    z, y, x = mask.shape
    mask[z // 4 : 3 * z // 4, y // 4 : 3 * y // 4, x // 4 : 3 * x // 4] = 1
    return reader, mask


def _legacy_write(output_path: Path, mask: np.ndarray, reader: OmeZarrReader) -> None:
    """The pre-feature-009 write: every level fully resized in memory, one uncompressed chunk."""
    group = zarr.open_group(str(output_path), mode="w", zarr_format=3)
    for i in range(reader.n_levels):
        level = _reference_nn_resize(mask, reader.level_shape(i))
        arr = group.create_array(
            str(i), shape=level.shape, dtype="uint8", chunks=level.shape, compressors=None
        )
        arr[:] = level


def test_write_memory_is_bounded(tmp_path, monkeypatch):
    """SC-001: writing a 32^3 run-level mask into a 512^3 finest level (128 MiB) stays far below
    that level's size under a scaled-down budget (8 MiB, 64^3 shards)."""
    import tracemalloc

    from organ_masker_lite.io import writer

    monkeypatch.setattr(writer, "WRITE_BUDGET_BYTES", 8 * 2**20)
    monkeypatch.setattr(writer, "DEFAULT_MAX_SHARD", 64)
    vol = np.zeros((512, 512, 512), np.uint8)
    reader = OmeZarrReader(
        write_ome_zarr(tmp_path / "big.ome.zarr", vol, n_levels=2, axis_factors=(16, 16, 16))
    )
    del vol
    assert reader.level_shape(1) == (32, 32, 32)
    mask = np.zeros((32, 32, 32), np.uint8)
    mask[8:24, 8:24, 8:24] = 1

    tracemalloc.start()
    writer.write_mask(tmp_path / "out.ome.zarr", mask, 1, reader, {})
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 32 * 2**20, f"peak {peak / 2**20:.1f} MiB for a 128 MiB level"


def test_write_time_within_legacy(tmp_path):
    """SC-005: the scalable writer takes at most 1.25x the legacy writer on the same machine.

    Runs are interleaved (legacy, new, legacy, new, ...) so drift in machine load affects both
    sides equally; medians of 5 each.
    """
    import shutil
    import statistics
    import time

    from organ_masker_lite.io.writer import write_mask

    reader, mask = _reference_fixture(tmp_path)
    legacy, new = [], []
    for i in range(5):
        a, b = tmp_path / f"legacy{i}.zarr", tmp_path / f"new{i}.zarr"
        t0 = time.perf_counter()
        _legacy_write(a, mask, reader)
        legacy.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        write_mask(b, mask, 1, reader, {})
        new.append(time.perf_counter() - t0)
        shutil.rmtree(a)
        shutil.rmtree(b)
    ratio = statistics.median(new) / statistics.median(legacy)
    assert ratio <= 1.25, (
        f"new {statistics.median(new):.3f}s vs legacy {statistics.median(legacy):.3f}s"
    )
