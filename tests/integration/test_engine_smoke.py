"""Engine smoke test: real-SAM2 single-axis pipeline end-to-end (T013)."""

from __future__ import annotations

import pytest

from ome_zarr_masker.config import RunConfig
from ome_zarr_masker.engine.pipeline import run_masking
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.prompts.model import Prompt, PromptSet

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_pipeline_produces_mask_with_matching_levels(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr
    prompts = PromptSet([Prompt(frame_index=frame, point_coords=[[cx, cy]], point_labels=[1])])
    cfg = RunConfig(axes=["z"], level=0)
    out = run_masking(store, tmp_path / "out.ome.zarr", prompts, cfg)

    in_reader = OmeZarrReader(store)
    out_reader = OmeZarrReader(out)
    assert out_reader.n_levels == in_reader.n_levels
    mask = out_reader.read_level(0)
    assert mask.any()
    assert mask.shape == in_reader.level_shape(0)
