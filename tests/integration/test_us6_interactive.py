"""US6: interactive masking session (T053, FR-009, FR-011).

The headless session core (prompt placement, preview, export over the shared engine) is verified
against real SAM2. The napari GUI is exercised only when napari is installed; its absence is
covered by asserting a clear, actionable import error (that check happens before SAM2 is ever
touched, so it needs no real backend).
"""

from __future__ import annotations

import importlib.util
import json

import numpy as np
import pytest

from organ_masker_lite.config import RunConfig
from organ_masker_lite.engine.pipeline import compute_mask
from organ_masker_lite.interactive import InteractiveSession
from organ_masker_lite.io.reader import OmeZarrReader
from organ_masker_lite.io.validate import validate_ome_zarr
from organ_masker_lite.prompts.model import load_prompt_file

from ..conftest import sam2_available

_HAVE_NAPARI = importlib.util.find_spec("napari") is not None
_HAVE_SAM2 = sam2_available()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_session_preview_updates_and_exports(two_blob_zarr, tmp_path):
    store, (ax, ay), (bx, by), frame = two_blob_zarr
    session = InteractiveSession(store, level=0)

    # place positive landmarks on both blobs; preview includes blob B
    session.add_positive_point(frame, ax, ay)
    session.add_positive_point(frame, bx, by)
    preview1 = session.preview(axes=["z"]).array
    assert preview1[frame, int(by), int(bx)] == 1

    # add a negative landmark on blob B; preview updates to exclude it, keeping blob A
    session.add_negative_point(frame, bx, by)
    preview2 = session.preview(axes=["z"]).array
    assert preview2[frame, int(by), int(bx)] == 0
    assert preview2[frame, int(ay), int(ax)] == 1

    # export the satisfactory preview as a valid OME-Zarr v0.5 mask
    out = session.export(tmp_path / "interactive.ome.zarr")
    validate_ome_zarr(out)
    assert OmeZarrReader(out).n_levels == OmeZarrReader(store).n_levels
    assert OmeZarrReader(out).read_level(0)[frame, int(by), int(bx)] == 0


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_export_without_explicit_preview_computes_one(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr
    session = InteractiveSession(store, level=0)
    session.add_positive_point(frame, cx, cy)

    out = session.export(tmp_path / "auto.ome.zarr")
    validate_ome_zarr(out)
    assert OmeZarrReader(out).read_level(0)[frame, int(cy), int(cx)] == 1


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_export_forces_full_recompute_even_with_cached_partial_preview(single_blob_zarr, tmp_path):
    """feature 007, FR-008/C-PV-9: export() must never reuse a cached partial preview."""
    store, (cx, cy), frame = single_blob_zarr
    session = InteractiveSession(store, level=0)
    session.add_positive_point(frame, cx, cy)

    # a narrow, single-slice-equivalent preview leaves self._preview holding a PARTIAL result
    partial = session.preview(axes=["z"], frame_range=(frame, frame)).array
    assert partial[frame].any()
    assert not partial[:frame].any()
    assert not partial[frame + 1 :].any()

    out = session.export(tmp_path / "safe.ome.zarr")
    validate_ome_zarr(out)
    exported = OmeZarrReader(out).read_level(0)

    # export MUST have recomputed the full whole-volume result, not reused the partial one
    full = session.preview(axes=["z"]).array
    assert np.array_equal(exported, full.astype(exported.dtype))
    assert not np.array_equal(exported, partial.astype(exported.dtype))


def test_add_box_replaces_existing_box_for_same_frame(single_blob_zarr):
    """feature 006, FR-010/C-UI-14: at most one box per frame; the newest replaces the old."""
    store, _center, frame = single_blob_zarr
    session = InteractiveSession(store, level=0)
    session.add_box(frame, [0, 0, 4, 4])
    session.add_box(frame, [1, 1, 5, 5])
    assert len(session._boxes) == 1
    assert session._boxes[frame].tolist() == [1, 1, 5, 5]

    session.clear_boxes()
    assert session._boxes == {}


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_box_only_prompt_reaches_the_masking_engine(single_blob_zarr):
    """feature 006: a box with no points still produces a mask (OrganMaskPredictor.add_box path)."""
    store, (cx, cy), frame = single_blob_zarr
    session = InteractiveSession(store, level=0)
    session.add_box(frame, [cx - 5, cy - 5, cx + 5, cy + 5])
    result = session.preview(axes=["z"])
    assert result.array[frame].any()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_interactive_point_and_box_match_equivalent_cli_prompt(single_blob_zarr, tmp_path):
    """feature 006, SC-004/C-UI-15: interactive point+box on one frame == CLI prompt-file both."""
    store, (cx, cy), frame = single_blob_zarr
    box = [cx - 6, cy - 6, cx + 6, cy + 6]

    session = InteractiveSession(store, level=0)
    session.add_positive_point(frame, cx, cy)
    session.add_box(frame, box)
    interactive_mask = session.preview(axes=["z"]).array

    prompts_path = tmp_path / "prompts.json"
    prompts_path.write_text(
        json.dumps(
            {
                "level": 0,
                "objects": [
                    {
                        "obj_id": 0,
                        "points": [{"frame": frame, "xy": [cx, cy], "label": 1}],
                        "box": {"frame": frame, "xyxy": box},
                    }
                ],
            }
        )
    )
    prompts = load_prompt_file(prompts_path)
    cli_result = compute_mask(store, prompts, RunConfig(axes=["z"], level=0))

    assert np.array_equal(interactive_mask.astype("uint8"), cli_result.consensus.astype("uint8"))


@pytest.mark.skipif(_HAVE_NAPARI, reason="napari is installed; the missing-extra path cannot run")
def test_launch_without_napari_raises_clear_error(single_blob_zarr):
    store, _center, _frame = single_blob_zarr
    session = InteractiveSession(store, level=0)
    with pytest.raises(ImportError, match="interactive"):
        session.launch()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_NAPARI, reason="napari not installed")
def test_launch_smoke_with_napari(single_blob_zarr):
    # When napari is available this constructs the session; full GUI launch needs a display.
    store, _center, _frame = single_blob_zarr
    session = InteractiveSession(store, level=0)
    assert session.read_volume().ndim == 3
