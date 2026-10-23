"""Python API and interactive session on remote stores (feature 010 US2/US3, T017/T023).

SAM2 is replaced by ``StubBackend`` (these tests check I/O rules, not segmentation). Covers
C-R-API-1…3, C-R-CLI-9 and FR-004.
"""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest

from ome_zarr_masker.api import OrganMaskPredictor
from ome_zarr_masker.cli import main
from ome_zarr_masker.interactive import InteractiveSession
from ome_zarr_masker.io.location import RemoteStoreError
from ome_zarr_masker.io.reader import OmeZarrReader

from ..conftest import StubBackend, write_ome_zarr


class _CountingStub(StubBackend):
    calls = 0

    def segment_video(self, frames, prompts):
        type(self).calls += 1
        return super().segment_video(frames, prompts)


@pytest.fixture(autouse=True)
def stub_sam2(monkeypatch):
    from ome_zarr_masker.engine import pipeline

    _CountingStub.calls = 0
    monkeypatch.setattr(pipeline, "Sam2Backend", lambda config=None: _CountingStub())


def _blob_volume() -> np.ndarray:
    vol = np.zeros((8, 16, 16), dtype=np.uint8)
    vol[2:6, 4:12, 4:12] = 200
    return vol


@pytest.fixture
def served(http_store_server, tmp_path):
    """``(local_store, url)``: the blob fixture and an HTTP-served copy of it."""
    local = write_ome_zarr(tmp_path / "in.ome.zarr", _blob_volume())
    shutil.copytree(local, http_store_server.root / "in.ome.zarr")
    return local, http_store_server.url("in.ome.zarr")


def _session(store) -> InteractiveSession:
    s = InteractiveSession(store, level=0)
    s.add_positive_point(4, 8.0, 8.0)
    return s


# -- US2: reading ------------------------------------------------------------------------------


def test_session_on_remote_input_matches_local(served):
    """US2 scenario 1 / C-R-CLI-9: same volume and same preview as a local store."""
    local, url = served
    remote, here = _session(url), _session(local)
    np.testing.assert_array_equal(remote.read_volume(), here.read_volume())
    np.testing.assert_array_equal(remote.preview().array, here.preview().array)
    few = (3, 5)
    np.testing.assert_array_equal(
        remote.preview(frame_range=few).array, here.preview(frame_range=few).array
    )


def test_session_prompts_reusable_by_mask_on_url_and_local_copy(served, tmp_path):
    """US2 scenario 2: prompts placed on the remote store stay local and give the same mask
    when run by ``mask`` on the URL or on a local copy."""
    local, url = served
    preview = _session(url).preview().array

    prompts = tmp_path / "prompts.json"
    prompts.write_text(
        json.dumps(
            {
                "level": 0,
                "objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}],
            }
        )
    )
    outs = []
    for name, src in (("url", url), ("local", str(local))):
        out = tmp_path / f"{name}.ome.zarr"
        assert main(["mask", src, str(out), "--prompts", str(prompts), "--level", "0"]) == 0
        outs.append(OmeZarrReader(out).read_level(0))
    np.testing.assert_array_equal(outs[0], outs[1])
    np.testing.assert_array_equal(outs[0], preview.astype(np.uint8))


def test_predictor_set_volume_reads_remote(served):
    local, url = served
    p = OrganMaskPredictor().set_volume(url, level=0)
    p.add_prompts(frame_index=4, point_coords=[[8.0, 8.0]], point_labels=[1])
    q = OrganMaskPredictor().set_volume(local, level=0)
    q.add_prompts(frame_index=4, point_coords=[[8.0, 8.0]], point_labels=[1])
    np.testing.assert_array_equal(p.predict(axes=["z"]).array, q.predict(axes=["z"]).array)


@pytest.mark.parametrize("dest", ["s3://bkt/m.ome.zarr", "https://example.org/m.ome.zarr"])
def test_export_to_remote_is_refused_before_any_work(served, tmp_path, dest):
    """C-R-API-3 / FR-004: refused before computing or writing anything."""
    _, url = served
    session = _session(url)
    _CountingStub.calls = 0
    with pytest.raises(RemoteStoreError) as exc:
        session.export(dest)
    assert exc.value.cause == "not_writable"
    assert "mask" in str(exc.value) and "MaskResult.save" in str(exc.value)
    assert _CountingStub.calls == 0


def test_export_to_local_path_unchanged(served, tmp_path):
    _, url = served
    out = _session(url).export(tmp_path / "out.ome.zarr")
    assert OmeZarrReader(out).read_level(0).any()
