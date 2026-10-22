"""US1 second feature: a bounding-box prompt yields foreground within the box (T027, C-CLI-2)."""

from __future__ import annotations

import numpy as np
import pytest

from ome_zarr_masker.config import RunConfig
from ome_zarr_masker.engine.pipeline import run_masking
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.prompts.model import Prompt, PromptSet

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_box_mask_foreground_within_box(single_blob_zarr, tmp_path):
    store, _center, frame = single_blob_zarr
    # blob occupies x in [4, 12), y in [4, 12); draw a box that encloses it
    box = [4.0, 4.0, 12.0, 12.0]
    prompts = PromptSet(
        [Prompt(frame_index=frame, point_coords=np.empty((0, 2)), point_labels=[], box=box)]
    )
    cfg = RunConfig(axes=["z"], level=0)

    out = run_masking(store, tmp_path / "out.ome.zarr", prompts, cfg)

    mask = OmeZarrReader(out).read_level(0)
    assert mask.any()
    # every foreground voxel lies within the box's in-plane (x, y) extent
    _z, ys, xs = np.nonzero(mask)
    x0, y0, x1, y1 = box
    assert (xs >= x0).all() and (xs < x1).all()
    assert (ys >= y0).all() and (ys < y1).all()
