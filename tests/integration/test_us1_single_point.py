"""US1 first feature: single positive point produces a mask including that point (T026)."""

from __future__ import annotations

import pytest

from organ_masker_lite.config import RunConfig
from organ_masker_lite.engine.pipeline import run_masking
from organ_masker_lite.io.reader import OmeZarrReader
from organ_masker_lite.prompts.model import Prompt, PromptSet

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_single_point_mask_includes_point(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr
    prompts = PromptSet([Prompt(frame_index=frame, point_coords=[[cx, cy]], point_labels=[1])])
    cfg = RunConfig(axes=["z"], level=0)

    out = run_masking(store, tmp_path / "out.ome.zarr", prompts, cfg)

    in_reader = OmeZarrReader(store)
    out_reader = OmeZarrReader(out)
    assert out_reader.n_levels == in_reader.n_levels
    mask = out_reader.read_level(0)
    # foreground present and the prompted voxel (frame, y, x) is included
    assert mask.any()
    assert mask[frame, int(cy), int(cx)] == 1
