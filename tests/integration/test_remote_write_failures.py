"""Remote write failure safety (feature 010 US3, T022: FR-009, SC-005, C-R-CLI-5).

``memory_fs`` routes ``s3://`` to an in-memory filesystem that can fail after N writes. After any
failure the output must not read as a valid store: it has no root ``zarr.json``.
"""

from __future__ import annotations

import numpy as np
import pytest

from ome_zarr_masker.io.location import RemoteStoreError
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.io.validate import ValidationError, validate_ome_zarr
from ome_zarr_masker.io.writer import write_mask

from ..conftest import write_ome_zarr

OUT = "s3://out-bkt/m.ome.zarr"
ROOT = "out-bkt/m.ome.zarr/zarr.json"


@pytest.fixture
def source(tmp_path):
    vol = np.zeros((16, 32, 32), dtype=np.uint8)
    vol[2:14, 4:28, 4:28] = 200
    reader = OmeZarrReader(write_ome_zarr(tmp_path / "in.ome.zarr", vol, n_levels=3))
    return reader, vol > 100


def _write(source, overwrite=False):
    reader, mask = source
    return write_mask(OUT, mask, 0, reader, {"tool": "test"}, overwrite=overwrite)


def _keys(memory_fs) -> set[str]:
    return {k.lstrip("/") for k in memory_fs.fs.find("/out-bkt")}


def test_successful_write_puts_root_document_last(memory_fs, source):
    assert _write(source) == OUT
    puts = [p.lstrip("/") for p in memory_fs.puts]
    assert puts[-1] == ROOT
    # ``to_zarr`` writes the root document while building the metadata (it is then withheld);
    # it is never put again until every shard and the run record are in place
    first_shard = next(i for i, p in enumerate(puts) if "/c/" in p)
    assert all(i < first_shard for i, p in enumerate(puts[:-1]) if p == ROOT)
    assert puts.index("out-bkt/m.ome.zarr/run_record.json") > max(
        i for i, p in enumerate(puts) if "/c/" in p
    )
    validate_ome_zarr(OUT)
    reader, mask = source
    np.testing.assert_array_equal(OmeZarrReader(OUT).read_level(0), mask.astype(np.uint8))


def _assert_not_a_store(memory_fs):
    assert ROOT not in _keys(memory_fs)
    with pytest.raises((ValidationError, RemoteStoreError)):
        validate_ome_zarr(OUT)


@pytest.mark.parametrize("which", ["first", "middle", "last"])
def test_failed_write_never_reads_as_a_store(memory_fs, source, which):
    _write(source)
    total = len(memory_fs.puts)
    memory_fs.fs.rm("/out-bkt", recursive=True)
    memory_fs.puts.clear()

    n = {"first": 0, "middle": total // 2, "last": total - 1}[which]
    memory_fs.fail_after(n)
    with pytest.raises(RemoteStoreError) as exc:
        _write(source)
    assert exc.value.cause == "network" and exc.value.location == OUT
    assert OUT in str(exc.value)
    memory_fs.fail_after(None)
    _assert_not_a_store(memory_fs)


def test_failed_overwrite_leaves_no_store(memory_fs, source):
    """C-R-CLI-4 note: the old store is gone, and the failed new one doesn't read as a store."""
    _write(source)
    memory_fs.puts.clear()
    memory_fs.fail_after(3)
    with pytest.raises(RemoteStoreError):
        _write(source, overwrite=True)
    memory_fs.fail_after(None)
    _assert_not_a_store(memory_fs)


def test_leftovers_of_a_failed_write_are_replaced(memory_fs, source):
    """A prefix with no root document isn't a store: a new write needs no overwrite, and no
    stale shard from the failed attempt survives into the new output."""
    reader, mask = source
    memory_fs.fail_after(5)
    with pytest.raises(RemoteStoreError):
        write_mask(OUT, ~mask, 0, reader, {"tool": "test"})
    memory_fs.fail_after(None)
    memory_fs.fs.pipe_file("/out-bkt/m.ome.zarr/0/c/9/9/9", b"stale")  # as if cleanup failed
    _write(source)
    assert "out-bkt/m.ome.zarr/0/c/9/9/9" not in _keys(memory_fs)
    np.testing.assert_array_equal(OmeZarrReader(OUT).read_level(0), mask.astype(np.uint8))
