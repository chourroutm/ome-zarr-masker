"""US2: multi-axis sweeps seeded from the prompted axis (T038, FR-007, FR-022, SC-003).

Landmarks are placed on a single (z) plane; the z axis is swept first and the y/x sweeps are
seeded automatically from its 3D mask. The multi-axis majority consensus must agree at least as
much as the single-axis forward-only result (a broken seeding would shrink the consensus).
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


def _run(store, out, axes):
    prompts = PromptSet([Prompt(frame_index=4, point_coords=[[8.0, 8.0]], point_labels=[1])])
    cfg = RunConfig(axes=axes, level=0, combine_rule="majority")
    return run_masking(store, out, prompts, cfg)


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_multiaxis_consensus_at_least_single_axis(single_blob_zarr, tmp_path):
    store, _center, _frame = single_blob_zarr

    single = OmeZarrReader(_run(store, tmp_path / "single.ome.zarr", ["z"])).read_level(0)
    multi_path = _run(store, tmp_path / "multi.ome.zarr", ["z", "y", "x"])
    multi = OmeZarrReader(multi_path).read_level(0)

    # output is valid with the input's level count
    assert OmeZarrReader(multi_path).n_levels == OmeZarrReader(store).n_levels
    assert single.any() and multi.any()
    # seeded multi-axis consensus covers everything the single-axis sweep found
    assert np.array_equal(multi | single, multi)
    assert multi.sum() >= single.sum()
