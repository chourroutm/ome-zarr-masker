"""US6: interactive masking session (T053, FR-009, FR-011).

The headless session core (prompt placement, preview, export over the shared engine) is verified
against real SAM2. The napari GUI is exercised only when napari is installed; its absence is
covered by asserting a clear, actionable import error (that check happens before SAM2 is ever
touched, so it needs no real backend).
"""

from __future__ import annotations

import importlib.util

import pytest

from organ_masker_lite.interactive import InteractiveSession
from organ_masker_lite.io.reader import OmeZarrReader
from organ_masker_lite.io.validate import validate_ome_zarr

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
