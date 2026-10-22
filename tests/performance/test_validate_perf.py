"""T009: in-process OME-Zarr validation is fast and spawns no sub-process (feature 003).

In-process validation replaces a subprocess invocation of the ``ome-zarr-models`` console script, so
per-run validation time must not increase (SC-005, C-VAL-7). The budget is generous relative to the
prior interpreter sub-process startup cost; the point is to guard against a regression to spawning a
process.
"""

from __future__ import annotations

import subprocess
import time

import numpy as np

from ome_zarr_masker.io.validate import validate_ome_zarr

from ..conftest import write_ome_zarr

BUDGET_S = 0.500


def _valid_store(tmp_path):
    vol = np.zeros((8, 16, 16), np.uint8)
    vol[2:6, 4:12, 4:12] = 200
    return write_ome_zarr(tmp_path / "in.ome.zarr", vol)


def test_validation_under_budget(tmp_path):
    store = _valid_store(tmp_path)
    best = min(_time_once(store) for _ in range(5))
    assert best < BUDGET_S, f"validation took {best * 1000:.1f} ms, over {BUDGET_S * 1000:.0f} ms"


def test_validation_spawns_no_subprocess(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("validation must not spawn a subprocess")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    validate_ome_zarr(_valid_store(tmp_path))


def _time_once(store):
    start = time.perf_counter()
    validate_ome_zarr(store)
    return time.perf_counter() - start
