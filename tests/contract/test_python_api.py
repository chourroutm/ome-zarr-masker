"""Python API contract tests for OrganMaskPredictor (T046, contracts/python-api.md C-API-1..8).

SAM2 is the only backend; there is no `backend` constructor parameter. Tests that only exercise
argument validation before segmentation runs need no real backend. Tests that run the pipeline to
completion are marked ``real_backend`` and require a real, GPU-powered SAM2 install to actually
execute (skipped otherwise).
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from ome_zarr_masker import OrganMaskPredictor
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.io.validate import validate_ome_zarr
from ome_zarr_masker.prompts.model import PromptError

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()
requires_sam2 = pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")


def _predictor(store, level=0):
    return OrganMaskPredictor().set_volume(store, level=level)


@pytest.mark.real_backend
@requires_sam2
def test_c_api_1_single_point_includes_point(single_blob_zarr):
    store, (cx, cy), frame = single_blob_zarr
    p = _predictor(store)
    p.add_prompts(frame_index=frame, point_coords=[[cx, cy]], point_labels=[1])
    result = p.predict(axes=["z"])
    assert result.array.any()
    assert result.array[frame, int(cy), int(cx)] == 1


@pytest.mark.real_backend
@requires_sam2
def test_c_api_2_box_foreground_within_box(single_blob_zarr):
    store, _center, frame = single_blob_zarr
    box = [4.0, 4.0, 12.0, 12.0]
    p = _predictor(store)
    p.add_box(frame_index=frame, box=box)
    result = p.predict(axes=["z"])
    assert result.array.any()
    _z, ys, xs = np.nonzero(result.array)
    x0, y0, x1, y1 = box
    assert (xs >= x0).all() and (xs < x1).all()
    assert (ys >= y0).all() and (ys < y1).all()


@pytest.mark.real_backend
@requires_sam2
def test_c_api_3_negative_point_excludes_region(two_blob_zarr):
    store, (ax, ay), (bx, by), frame = two_blob_zarr
    p = _predictor(store)
    p.add_prompts(
        frame_index=frame,
        point_coords=[[ax, ay], [bx, by], [bx, by]],
        point_labels=[1, 1, 0],
    )
    result = p.predict(axes=["z"])
    assert result.array[frame, int(ay), int(ax)] == 1
    assert result.array[frame, int(by), int(bx)] == 0


def test_c_api_4_no_positive_prompt_raises(single_blob_zarr):
    store, _center, _frame = single_blob_zarr
    p = _predictor(store)
    with pytest.raises(PromptError):
        p.predict(axes=["z"])


def test_c_api_5_out_of_bounds_raises(single_blob_zarr):
    store, _center, frame = single_blob_zarr
    p = _predictor(store)
    p.add_prompts(frame_index=frame, point_coords=[[999, 999]], point_labels=[1])
    with pytest.raises(PromptError):
        p.predict(axes=["z"])


@pytest.mark.real_backend
@requires_sam2
def test_c_api_6_saved_output_valid_same_levels(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr
    p = _predictor(store)
    p.add_prompts(frame_index=frame, point_coords=[[cx, cy]], point_labels=[1])
    out = p.predict(axes=["z"]).save(tmp_path / "api_out.ome.zarr")

    validate_ome_zarr(out)  # valid OME-Zarr v0.5
    assert OmeZarrReader(out).n_levels == OmeZarrReader(store).n_levels


def test_c_api_7_argument_names_and_shapes_match_sam2():
    points_params = list(inspect.signature(OrganMaskPredictor.add_prompts).parameters)
    box_params = list(inspect.signature(OrganMaskPredictor.add_box).parameters)
    # SAM2-style prompt arguments. `box` (feature 006, keyword-only) lets a caller combine a
    # frame's points and box into one call -- required so SAM2 doesn't silently drop one or the
    # other (research R2); `add_box` is unchanged, still a valid box-only call.
    assert points_params == ["self", "frame_index", "point_coords", "point_labels", "obj_id", "box"]
    assert box_params == ["self", "frame_index", "box", "obj_id"]


def test_c_api_8_backend_kwarg_rejected():
    """C-API-8: backend no longer exists as a parameter; passing it is a standard TypeError."""
    with pytest.raises(TypeError, match="backend"):
        OrganMaskPredictor(backend="sam3")
