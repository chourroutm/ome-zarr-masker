"""Reading OME-Zarr inputs over HTTP(S) (feature 010 US1, T009).

A local Range-capable HTTP server serves fixture stores (``http_store_server``). Segmentation uses
``StubBackend``: these tests check that a remote input gives the same output as a local copy, not
segmentation quality. Covers C-R-CLI-2, FR-006, FR-007, FR-008/SC-002, FR-010/C-LOC-7.
"""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest

from ome_zarr_masker.config import RunConfig
from ome_zarr_masker.engine.pipeline import run_masking
from ome_zarr_masker.io.location import RemoteStoreError
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.io.validate import ValidationError, validate_ome_zarr
from ome_zarr_masker.prompts.model import Prompt, PromptSet

from ..conftest import StubBackend, write_ome_zarr


def _blob_volume() -> np.ndarray:
    vol = np.zeros((8, 16, 16), dtype=np.uint8)
    vol[2:6, 4:12, 4:12] = 200
    return vol


def _prompts() -> PromptSet:
    return PromptSet([Prompt(frame_index=4, point_coords=[[8.0, 8.0]], point_labels=[1])])


def _served_copy(server, local, name="vol.ome.zarr") -> str:
    shutil.copytree(local, server.root / name)
    return server.url(name)


def _levels(path) -> list[np.ndarray]:
    reader = OmeZarrReader(path)
    return [reader.read_level(i) for i in range(reader.n_levels)]


def test_reader_and_validator_match_local(http_store_server, tmp_path):
    local = write_ome_zarr(tmp_path / "in.ome.zarr", _blob_volume(), n_levels=3)
    url = _served_copy(http_store_server, local)

    validate_ome_zarr(url)
    remote, here = OmeZarrReader(url), OmeZarrReader(local)
    assert remote.n_levels == here.n_levels and remote.axes == here.axes
    for i in range(here.n_levels):
        assert remote.level_shape(i) == here.level_shape(i)
        assert remote.level_transform(i) == here.level_transform(i)
        np.testing.assert_array_equal(remote.read_level(i), here.read_level(i))


def test_remote_input_output_equals_local_input_output(http_store_server, tmp_path):
    """C-R-CLI-2 / FR-007 / SC-001: same data, metadata and layout; record differs in input only."""
    local = write_ome_zarr(tmp_path / "in.ome.zarr", _blob_volume())
    url = _served_copy(http_store_server, local)
    cfg = RunConfig(axes=["z"], level=0)

    out_local = run_masking(local, tmp_path / "a.ome.zarr", _prompts(), cfg, backend=StubBackend())
    out_remote = run_masking(url, tmp_path / "b.ome.zarr", _prompts(), cfg, backend=StubBackend())

    for a, b in zip(_levels(out_local), _levels(out_remote), strict=True):
        np.testing.assert_array_equal(a, b)
    assert (out_local / "zarr.json").read_text() == (out_remote / "zarr.json").read_text()
    rec_a = json.loads((out_local / "run_record.json").read_text())
    rec_b = json.loads((out_remote / "run_record.json").read_text())
    assert rec_b["input"] == url
    assert rec_a["input"] == str(local)
    for rec in (rec_a, rec_b):
        rec.pop("input")
        rec.pop("run_id", None)
    assert rec_a == rec_b


def test_remote_read_fetches_only_the_selected_level(http_store_server, tmp_path):
    """SC-002 / FR-008: a coarse-level read transfers that level plus metadata, within 10%.

    Metadata documents are fetched a few times (validation, then the reader), so the level is
    made large enough that, as with real pyramids, its data dominates the transfer.
    """
    rng = np.random.default_rng(0)
    vol = rng.integers(0, 255, size=(128, 128, 128), dtype=np.uint8)  # incompressible
    local = write_ome_zarr(tmp_path / "big.ome.zarr", vol, n_levels=3)
    url = _served_copy(http_store_server, local, "big.ome.zarr")
    run_level = 1

    http_store_server.reset_counter()
    validate_ome_zarr(url)
    reader = OmeZarrReader(url)
    reader.read_level(reader.resolve_level(run_level))

    def size(paths) -> int:
        return sum(p.stat().st_size for p in paths if p.is_file())

    level_bytes = size((local / str(run_level)).rglob("*"))
    metadata_bytes = size(local.rglob("zarr.json"))
    assert http_store_server.bytes_served <= 1.10 * (level_bytes + metadata_bytes)
    chunk_requests = [r for r in http_store_server.counter["requests"] if "/c/" in r]
    assert chunk_requests and all(f"/big.ome.zarr/{run_level}/c/" in r for r in chunk_requests)


def test_missing_remote_store_is_not_found(http_store_server):
    url = http_store_server.url("missing.ome.zarr")
    with pytest.raises(RemoteStoreError) as exc:
        validate_ome_zarr(url)
    assert exc.value.cause == "not_found"
    assert not isinstance(exc.value, ValidationError)
    assert url in str(exc.value)


def test_unreachable_server_is_network_error(http_store_server, tmp_path):
    local = write_ome_zarr(tmp_path / "in.ome.zarr", _blob_volume())
    url = _served_copy(http_store_server, local)
    http_store_server.stop()
    with pytest.raises(RemoteStoreError) as exc:
        validate_ome_zarr(url)
    assert exc.value.cause == "network"
    assert url in str(exc.value)


def test_network_loss_while_reading_is_a_remote_error(http_store_server, tmp_path):
    """Edge case: the network drops during reading -> a clear error, not a partial result."""
    local = write_ome_zarr(tmp_path / "in.ome.zarr", _blob_volume())
    url = _served_copy(http_store_server, local)
    reader = OmeZarrReader(url)
    http_store_server.stop()
    with pytest.raises(RemoteStoreError) as exc:
        reader.read_level(0)
    assert exc.value.cause == "network"


def test_remote_v04_store_gets_the_local_version_message(http_store_server, tmp_path):
    """FR-006: same validation rules and message as for a local store."""
    store = http_store_server.root / "v04.ome.zarr"
    store.mkdir()
    (store / ".zgroup").write_text('{"zarr_format": 2}')
    (store / ".zattrs").write_text(
        '{"multiscales": [{"version": "0.4", "axes": [], "datasets": []}]}'
    )
    url = http_store_server.url("v04.ome.zarr")
    with pytest.raises(ValidationError) as remote_exc:
        validate_ome_zarr(url)
    with pytest.raises(ValidationError) as local_exc:
        validate_ome_zarr(store)
    assert str(remote_exc.value) == str(local_exc.value).replace(str(store), url)
    assert "requires OME-Zarr v0.5" in str(remote_exc.value)


def test_remote_junk_store_is_a_validation_error(http_store_server):
    store = http_store_server.root / "junk.ome.zarr"
    store.mkdir()
    (store / "zarr.json").write_text('{"zarr_format": 3, "node_type": "group"}')
    with pytest.raises(ValidationError):
        validate_ome_zarr(http_store_server.url("junk.ome.zarr"))
