"""Integration test for RunConfig.frame_range end-to-end (C-PV-12, research R3).

real_backend-gated, mirrors this project's existing pipeline integration tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from organ_masker_lite.config import RunConfig
from organ_masker_lite.engine.pipeline import compute_mask
from organ_masker_lite.prompts.model import load_prompt_file

from ..conftest import sam2_available, write_ome_zarr

_HAVE_SAM2 = sam2_available()


def _store(tmp_path: Path) -> Path:
    vol = np.zeros((10, 16, 16), np.uint8)
    vol[2:8, 4:12, 4:12] = 200
    return write_ome_zarr(tmp_path / "vol.ome.zarr", vol, n_levels=1)


def _prompts(tmp_path: Path) -> Path:
    path = tmp_path / "p.json"
    path.write_text(
        json.dumps(
            {
                "level": 0,
                "objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}],
            }
        )
    )
    return path


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_frame_range_matches_unbounded_within_range_and_zero_outside(tmp_path):
    store = _store(tmp_path)
    prompts = load_prompt_file(_prompts(tmp_path))

    full = compute_mask(store, prompts, RunConfig(axes=["z"], level=0))
    windowed = compute_mask(store, prompts, RunConfig(axes=["z"], level=0, frame_range=(2, 7)))

    assert windowed.consensus.shape == full.consensus.shape
    assert np.array_equal(windowed.consensus[2:8], full.consensus[2:8])
    assert windowed.consensus[:2].sum() == 0
    assert windowed.consensus[8:].sum() == 0
