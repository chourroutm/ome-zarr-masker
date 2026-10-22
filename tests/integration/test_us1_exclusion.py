"""US1 third feature: an exclusion point (label 0) removes that region (T028, C-CLI-3)."""

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
def test_exclusion_point_removes_region(two_blob_zarr, tmp_path):
    store, (ax, ay), (bx, by), frame = two_blob_zarr
    # select both blobs, then exclude blob B with a negative point
    prompts = PromptSet(
        [
            Prompt(
                frame_index=frame,
                point_coords=[[ax, ay], [bx, by], [bx, by]],
                point_labels=[1, 1, 0],
            )
        ]
    )
    cfg = RunConfig(axes=["z"], level=0)

    out = run_masking(store, tmp_path / "out.ome.zarr", prompts, cfg)

    mask = OmeZarrReader(out).read_level(0)
    assert mask.any()
    # blob A retained, blob B removed by the exclusion point
    assert mask[frame, int(ay), int(ax)] == 1
    assert mask[frame, int(by), int(bx)] == 0
