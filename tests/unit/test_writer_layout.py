"""Unit tests for the scalable mask writer's layout, worker and progress logic (feature 009)."""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

from organ_masker_lite.io import writer
from organ_masker_lite.io.writer import (
    LevelLayout,
    _array_spec,
    _default_layout,
    _shard_regions,
)

# -- default layout (FR-007, research R1) ----------------------------------------------------------


def test_default_layout_full_size_level():
    lay = _default_layout((7526, 6985, 6985))
    assert lay.chunks == (64, 64, 64)
    assert lay.shards == (1024, 1024, 1024)
    assert lay.source == "default"


@pytest.mark.parametrize(
    ("shape", "shards"),
    [((10, 100, 941), (64, 128, 960)), ((941, 874, 874), (960, 896, 896))],
)
def test_default_layout_rounds_shard_up_to_chunk_multiple_and_caps_at_level(shape, shards):
    assert _default_layout(shape).shards == shards


def test_shard_regions_tile_level_exactly_once():
    lay = LevelLayout(
        level=0, shape=(70, 33, 129), chunks=(16, 16, 16), shards=(32, 32, 64), source="default"
    )
    regions = list(_shard_regions(lay))
    assert len(regions) == math.prod(
        math.ceil(s / sh) for s, sh in zip(lay.shape, lay.shards, strict=True)
    )
    covered = np.zeros(lay.shape, np.int32)
    for r in regions:
        covered[r] += 1
    assert (covered == 1).all()  # every voxel covered once, ragged edges included


# -- array spec (FR-003, FR-004, research R1/R5) ----------------------------------------------


def test_array_spec_is_sharded_blosc_uint8_fill_zero():
    lay = LevelLayout(
        level=0,
        shape=(100, 200, 300),
        chunks=(64, 64, 64),
        shards=(128, 256, 320),
        source="default",
    )
    spec = _array_spec(lay, ["z", "y", "x"]).model_dump()
    assert spec["data_type"] == "uint8"
    assert spec["fill_value"] == 0
    assert list(spec["dimension_names"]) == ["z", "y", "x"]
    assert list(spec["chunk_grid"]["configuration"]["chunk_shape"]) == [128, 256, 320]
    sharding = spec["codecs"][0]
    assert sharding["name"] == "sharding_indexed"
    assert list(sharding["configuration"]["chunk_shape"]) == [64, 64, 64]
    inner = {c["name"]: c.get("configuration", {}) for c in sharding["configuration"]["codecs"]}
    assert inner["blosc"]["cname"] == "zstd"
    assert inner["blosc"]["clevel"] == 3
    assert inner["blosc"]["shuffle"] == "bitshuffle"


def test_module_constants_match_research():
    assert writer.DEFAULT_CHUNKS == (64, 64, 64)
    assert writer.DEFAULT_MAX_SHARD == 1024
    assert writer.WRITE_BUDGET_BYTES == 8 * 2**30


# -- worker resolution (FR-002, FR-011, research R3) -----------------------------------------------


def _layout(shards):
    return LevelLayout(
        level=0, shape=(4096, 4096, 4096), chunks=(64, 64, 64), shards=shards, source="default"
    )


def test_resolve_workers_budget_derived_by_default():
    import os

    from organ_masker_lite.io.writer import resolve_workers

    lay = _layout((1024, 1024, 1024))  # 1 GiB shard -> 8 GiB / 2 GiB per worker = 4
    assert resolve_workers(None, lay) == max(1, min(os.cpu_count() or 1, 4))


def test_resolve_workers_user_value_wins():
    from organ_masker_lite.io.writer import resolve_workers

    assert resolve_workers(3, _layout((1024, 1024, 1024))) == 3


@pytest.mark.parametrize("bad", [0, -1, 1.5, "2", True])
def test_resolve_workers_rejects_invalid(bad):
    from organ_masker_lite.io.writer import WriterError, resolve_workers

    with pytest.raises(WriterError):
        resolve_workers(bad, _layout((64, 64, 64)))


def test_resolve_workers_oversized_shard_falls_back_to_one_with_warning(monkeypatch):
    from organ_masker_lite.io.writer import resolve_workers

    monkeypatch.setattr(writer, "WRITE_BUDGET_BYTES", 2**20)
    with pytest.warns(UserWarning, match="budget"):
        assert resolve_workers(None, _layout((128, 128, 128))) == 1  # 2 MiB shard > 1 MiB budget


# -- validation before writing, concurrency cap (FR-011, SC-006) -----------------------------------


def _small_reader(tmp_path, shape=(8, 16, 16), n_levels=3):
    from organ_masker_lite.io.reader import OmeZarrReader

    from ..conftest import write_ome_zarr

    return OmeZarrReader(
        write_ome_zarr(tmp_path / "in.ome.zarr", np.zeros(shape, np.uint8), n_levels=n_levels)
    )


def test_invalid_workers_rejected_before_anything_is_written(tmp_path):
    from organ_masker_lite.io.writer import WriterError, write_mask

    reader = _small_reader(tmp_path)
    out = tmp_path / "out.ome.zarr"
    with pytest.raises(WriterError):
        write_mask(out, np.ones(reader.level_shape(0), np.uint8), 0, reader, {}, workers=0)
    assert not out.exists()
    assert not out.with_name(out.name + ".tmp").exists()


def test_concurrent_shards_never_exceed_workers(tmp_path, monkeypatch):
    import threading
    import time

    from organ_masker_lite.io.writer import write_mask

    monkeypatch.setattr(writer, "DEFAULT_CHUNKS", (4, 4, 4))
    monkeypatch.setattr(writer, "DEFAULT_MAX_SHARD", 4)
    real = writer._write_shard
    state = {"active": 0, "peak": 0}
    lock = threading.Lock()

    def tracked(*args, **kwargs):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            time.sleep(0.005)
            return real(*args, **kwargs)
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(writer, "_write_shard", tracked)
    reader = _small_reader(tmp_path)
    write_mask(
        tmp_path / "out.ome.zarr",
        np.ones(reader.level_shape(0), np.uint8),
        0,
        reader,
        {},
        workers=2,
    )
    assert 1 <= state["peak"] <= 2


# -- progress (FR-013, C-W-API-3) ------------------------------------------------------------------

_LEVEL_START = re.compile(r"writing level (\d+) .* (\d+) shards .* workers=(\d+) \((user|budget)\)")


def _write_with_progress(tmp_path, monkeypatch, workers):
    from organ_masker_lite.io.writer import write_mask

    monkeypatch.setattr(writer, "DEFAULT_CHUNKS", (4, 4, 4))
    monkeypatch.setattr(writer, "DEFAULT_MAX_SHARD", 4)
    reader = _small_reader(tmp_path)
    messages = []
    write_mask(
        tmp_path / "out.ome.zarr",
        np.ones(reader.level_shape(0), np.uint8),
        0,
        reader,
        {},
        workers=workers,
        progress=messages.append,
    )
    return reader, messages


def _per_level(messages):
    levels = {}
    current = None
    for m in messages:
        start = _LEVEL_START.search(m)
        if start:
            current = int(start.group(1))
            levels[current] = {"start": start, "progress": 0}
        elif current is not None:
            levels[current]["progress"] += 1
    return levels


def test_progress_one_start_and_at_most_ten_updates_per_level(tmp_path, monkeypatch, capsys):
    reader, messages = _write_with_progress(tmp_path, monkeypatch, workers=None)
    levels = _per_level(messages)
    assert sorted(levels) == list(range(reader.n_levels))
    for info in levels.values():
        n_shards = int(info["start"].group(2))
        assert info["start"].group(4) == "budget"
        assert 1 <= info["progress"] <= min(n_shards, 10)
        if n_shards < 10:
            assert info["progress"] == n_shards
    assert capsys.readouterr().out == ""


def test_progress_reports_user_worker_count(tmp_path, monkeypatch):
    _, messages = _write_with_progress(tmp_path, monkeypatch, workers=3)
    starts = [_LEVEL_START.search(m) for m in messages if _LEVEL_START.search(m)]
    assert starts and all(s.group(3) == "3" and s.group(4) == "user" for s in starts)


# -- run record layout, empty-shard skipping (US2: FR-012, FR-005) ---------------------------------


def test_run_record_has_output_layout_without_worker_count(tmp_path):
    import json

    from organ_masker_lite.io.writer import write_mask

    records = []
    for workers in (1, 4):
        reader = _small_reader(tmp_path / f"w{workers}")
        out = write_mask(
            tmp_path / f"w{workers}" / "out.ome.zarr",
            np.ones(reader.level_shape(0), np.uint8),
            0,
            reader,
            {"run": 1},
            workers=workers,
        )
        text = (out / "run_record.json").read_text()
        assert "worker" not in text
        records.append(json.loads(text))
    assert records[0] == records[1]
    layout = records[0]["output_layout"]
    assert [e["level"] for e in layout] == list(range(reader.n_levels))
    for entry in layout:
        assert set(entry) == {"level", "shape", "chunks", "shards", "compressor", "source"}
        assert entry["compressor"] == {
            "name": "blosc",
            "cname": "zstd",
            "clevel": 3,
            "shuffle": "bitshuffle",
        }
        assert entry["source"] == "default"
    assert records[0]["run"] == 1  # existing keys kept


def test_shards_with_no_foreground_are_never_built(tmp_path, monkeypatch):
    from organ_masker_lite.io.writer import write_mask

    monkeypatch.setattr(writer, "DEFAULT_CHUNKS", (4, 4, 4))
    monkeypatch.setattr(writer, "DEFAULT_MAX_SHARD", 4)
    counts = {"build": 0, "write": 0}
    real_build, real_write = writer._build_block, writer._write_shard

    def build(*a, **k):
        counts["build"] += 1
        return real_build(*a, **k)

    def write(*a, **k):
        counts["write"] += 1
        return real_write(*a, **k)

    monkeypatch.setattr(writer, "_build_block", build)
    monkeypatch.setattr(writer, "_write_shard", write)
    reader = _small_reader(tmp_path, n_levels=1)  # (8, 16, 16) -> 2 x 4 x 4 = 32 shards
    mask = np.zeros(reader.level_shape(0), np.uint8)
    mask[:4] = 1  # foreground only in the first z-half
    write_mask(tmp_path / "out.ome.zarr", mask, 0, reader, {}, workers=1)
    assert counts["write"] == 32
    assert counts["build"] == 16


# -- layout copied from sharded inputs (US3: FR-007, C-OUT-3) --------------------------------------


def test_plan_layouts_copies_sharded_input(tmp_path):
    from organ_masker_lite.io.reader import OmeZarrReader
    from organ_masker_lite.io.writer import plan_layouts, write_mask

    from ..conftest import assert_ome_zarr_models_valid, write_ome_zarr

    vol = np.zeros((40, 70, 70), np.uint8)
    reader = OmeZarrReader(
        write_ome_zarr(
            tmp_path / "s.ome.zarr", vol, n_levels=2, chunks=(16, 16, 16), shards=(32, 32, 32)
        )
    )
    layouts = plan_layouts(reader)
    for lay in layouts:
        assert lay.source == "input"
        assert (lay.chunks, lay.shards) == reader.level_storage(lay.level)

    mask = np.zeros(reader.level_shape(1), np.uint8)
    mask[5:15, 10:25, 10:25] = 1
    out = write_mask(tmp_path / "out.ome.zarr", mask, 1, reader, {})
    out_reader = OmeZarrReader(out)
    for lay in layouts:
        assert out_reader.level_storage(lay.level) == (lay.chunks, lay.shards)
    assert_ome_zarr_models_valid(out)


def test_plan_layouts_uses_default_for_unsharded_input(tmp_path):
    from organ_masker_lite.io.writer import _default_layout, plan_layouts

    reader = _small_reader(tmp_path)  # unsharded, single chunk per level
    for lay in plan_layouts(reader):
        assert lay.source == "default"
        assert lay == _default_layout(reader.level_shape(lay.level), lay.level)


def test_budget_worker_count_never_exceeds_level_shard_count(tmp_path, monkeypatch):
    """The reported (effective) budget-derived count is capped at the level's shard count."""
    _, messages = _write_with_progress(tmp_path, monkeypatch, workers=None)
    for m in messages:
        start = _LEVEL_START.search(m)
        if start:
            assert int(start.group(3)) <= int(start.group(2)), m
