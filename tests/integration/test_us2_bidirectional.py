"""US2: forward-and-reverse propagation merges both directions (T039, FR-006).

The forward_reverse pass runs the backend on the frame stack and its reverse, then unions the two.
The merged result must cover at least the forward-only result and stay a valid OME-Zarr mask.
"""

from __future__ import annotations

import numpy as np
import pytest

from ome_zarr_masker.config import RunConfig
from ome_zarr_masker.engine.pipeline import run_masking
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.prompts.model import Prompt, PromptSet

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()


def _run(store, out, direction):
    prompts = PromptSet([Prompt(frame_index=4, point_coords=[[8.0, 8.0]], point_labels=[1])])
    cfg = RunConfig(axes=["z"], level=0, direction=direction)
    return run_masking(store, out, prompts, cfg)


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_forward_reverse_merges_directions(single_blob_zarr, tmp_path):
    store, _center, _frame = single_blob_zarr

    forward = OmeZarrReader(_run(store, tmp_path / "fwd.ome.zarr", "forward")).read_level(0)
    both_path = _run(store, tmp_path / "both.ome.zarr", "forward_reverse")
    both = OmeZarrReader(both_path).read_level(0)

    assert OmeZarrReader(both_path).n_levels == OmeZarrReader(store).n_levels
    assert forward.any() and both.any()
    # the bidirectional result is the union of both passes -> superset of forward-only
    assert np.array_equal(both | forward, both)
