"""Unit tests for the OME-Zarr writer (T010)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.io.validate import validate_ome_zarr
from ome_zarr_masker.io.writer import WriterError, write_mask

from ..conftest import assert_ome_zarr_models_valid, write_ome_zarr


def _reference_nn_resize(mask: np.ndarray, target_shape: tuple[int, ...]) -> np.ndarray:
    """The pre-feature-009 writer's top-left nearest-neighbour resize, kept as a test oracle."""
    if mask.shape == tuple(target_shape):
        return mask
    idx = np.ix_(
        *[
            np.clip((np.arange(t) * s // max(t, 1)), 0, s - 1)
            for s, t in zip(mask.shape, target_shape, strict=True)
        ]
    )
    return mask[idx]


def _physical_nn_oracle(mask, src_scale, src_trans, dst_shape, dst_scale, dst_trans):
    """Brute-force physical nearest neighbour, written independently of the production code:
    each target voxel centre is placed in the run level and takes the nearest source centre,
    exact ties to the lower index."""
    per_axis = []
    for a, (s_dim, t_dim) in enumerate(zip(mask.shape, dst_shape, strict=True)):
        idx = []
        for i in range(t_dim):
            x = (i * dst_scale[a] + dst_trans[a] - src_trans[a]) / src_scale[a]
            lo = math.floor(x)
            pick = lo if x - lo <= 0.5 + 1e-9 else lo + 1
            idx.append(min(max(pick, 0), s_dim - 1))
        per_axis.append(np.array(idx, dtype=np.int64))
    return mask[np.ix_(*per_axis)]


def _reader(tmp_path, n_levels=3):
    vol = np.zeros((8, 16, 16), np.uint8)
    vol[2:6, 4:12, 4:12] = 200
    return OmeZarrReader(write_ome_zarr(tmp_path / "in.ome.zarr", vol, n_levels=n_levels))


def test_nn_resize_preserves_labels_and_shape():
    mask = np.zeros((8, 16, 16), bool)
    mask[2:6, 4:12, 4:12] = True
    out = _reference_nn_resize(mask, (4, 8, 8))
    assert out.shape == (4, 8, 8)
    assert out.dtype == bool
    assert out.any()


# -- per-level index vectors (FR-006, research R2) -------------------------------------------


def _vectors_oracle(src_shape, src_scale, src_trans, dst_shape, dst_scale, dst_trans):
    """Index vectors the brute-force oracle picks, recovered by resampling an index ramp."""
    out = []
    for a in range(3):
        ramp_shape = [1, 1, 1]
        ramp_shape[a] = src_shape[a]
        ramp = np.arange(src_shape[a]).reshape(ramp_shape)
        ones = [1, 1, 1]
        sub = _physical_nn_oracle(
            ramp,
            [src_scale[a] if i == a else 1.0 for i in range(3)],
            [src_trans[a] if i == a else 0.0 for i in range(3)],
            [dst_shape[a] if i == a else ones[i] for i in range(3)],
            [dst_scale[a] if i == a else 1.0 for i in range(3)],
            [dst_trans[a] if i == a else 0.0 for i in range(3)],
        )
        out.append(sub.reshape(-1))
    return out


def test_nn_indices_translation_free_matches_reference_resize():
    from ome_zarr_masker.io.writer import _nn_indices

    src = (16, 32, 32)
    for dst, dst_scale in [((8, 16, 16), (2, 2, 2)), ((32, 64, 64), (0.5, 0.5, 0.5))]:
        got = _nn_indices(src, (1, 1, 1), (0, 0, 0), dst, dst_scale, (0, 0, 0))
        ramp = np.arange(np.prod(src)).reshape(src)
        assert np.array_equal(ramp[np.ix_(*got)], _reference_nn_resize(ramp, dst))


def test_nn_indices_half_pixel_translations_non_exact_ratio_match_oracle():
    from ome_zarr_masker.io.writer import _nn_indices

    # DANDI 001278 y axis: level 3 (874) -> level 2 (1747) and level 4 (437), real transforms
    s3, t3 = 63.040823798627, 27.576411899313502
    cases = [((1747,), 31.538454493417287, 11.825227246708643), ((437,), 126.081647597254, 59.0968)]
    for (dst_dim,), sd, td in cases:
        src_shape, dst_shape = (874, 4, 4), (dst_dim, 4, 4)
        args = (src_shape, (s3, 1, 1), (t3, 0, 0), dst_shape, (sd, 1, 1), (td, 0, 0))
        got = _nn_indices(*args)
        want = _vectors_oracle(*args)
        assert np.array_equal(got[0], want[0])


def test_nn_indices_identity_tie_and_bounds():
    from ome_zarr_masker.io.writer import _nn_indices

    same = _nn_indices((5, 6, 7), (2, 2, 2), (1, 1, 1), (5, 6, 7), (2, 2, 2), (1, 1, 1))
    assert [v.tolist() for v in same] == [list(range(5)), list(range(6)), list(range(7))]
    # coarse voxel centres land exactly between two fine centres -> lower index
    down = _nn_indices((8, 1, 1), (1, 1, 1), (0, 0, 0), (4, 1, 1), (2, 1, 1), (0.5, 0, 0))
    assert down[0].tolist() == [0, 2, 4, 6]
    # indices never leave [0, src_dim)
    shifted = _nn_indices((4, 1, 1), (1, 1, 1), (0, 0, 0), (4, 1, 1), (1, 1, 1), (50, 0, 0))
    assert shifted[0].min() >= 0 and shifted[0].max() <= 3


def test_write_matches_input_level_count_and_validates(tmp_path):
    reader = _reader(tmp_path, n_levels=3)
    mask = np.zeros((8, 16, 16), bool)
    mask[2:6, 4:12, 4:12] = True
    out = write_mask(tmp_path / "out.ome.zarr", mask, 0, reader, {"k": "v"})
    out_reader = OmeZarrReader(out)
    assert out_reader.n_levels == reader.n_levels == 3
    assert out_reader.level_shape(0) == (8, 16, 16)
    validate_ome_zarr(out)  # no raise
    assert_ome_zarr_models_valid(out)
    assert (out / "run_record.json").exists()
    assert out_reader.read_level(0).max() == 1  # binary 0/1


def test_overwrite_guard(tmp_path):
    reader = _reader(tmp_path)
    mask = np.ones((8, 16, 16), bool)
    write_mask(tmp_path / "out.ome.zarr", mask, 0, reader, {})
    with pytest.raises(WriterError):
        write_mask(tmp_path / "out.ome.zarr", mask, 0, reader, {})
    # with overwrite it succeeds
    write_mask(tmp_path / "out.ome.zarr", mask, 0, reader, {}, overwrite=True)


# -- write_mask output equals the physical nearest-neighbour oracle (FR-006, SC-003) --------------


def _blob(shape, seed=0):
    rng = np.random.default_rng(seed)
    mask = np.zeros(shape, np.uint8)
    lo = [s // 4 for s in shape]
    hi = [max(lo_ + 1, 3 * s // 4) for lo_, s in zip(lo, shape, strict=True)]
    mask[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]] = 1
    mask[rng.random(shape) < 0.05] = 1  # scattered voxels exercise every index mapping
    return mask


def _assert_matches_oracle(out, reader, run_level, mask):
    run_scale, run_trans = reader.level_transform(run_level)
    out_reader = OmeZarrReader(out)
    assert out_reader.n_levels == reader.n_levels
    for i in range(reader.n_levels):
        scale, trans = reader.level_transform(i)
        expected = _physical_nn_oracle(
            mask, run_scale, run_trans, reader.level_shape(i), scale, trans
        )
        assert np.array_equal(out_reader.read_level(i), expected), f"level {i} differs"


def test_write_matches_oracle_translation_free(tmp_path):
    reader = _reader(tmp_path, n_levels=3)  # exact x2 ratios, no translations
    mask = _blob(reader.level_shape(1))
    out = write_mask(tmp_path / "out.ome.zarr", mask, 1, reader, {})
    _assert_matches_oracle(out, reader, 1, mask)
    out_reader = OmeZarrReader(out)
    for i in range(reader.n_levels):  # unchanged from the previous writer on such inputs
        assert np.array_equal(
            out_reader.read_level(i), _reference_nn_resize(mask, reader.level_shape(i))
        )
    validate_ome_zarr(out)
    assert_ome_zarr_models_valid(out)


def _dandi_style_reader(tmp_path):
    """Non-exact ratios and half-pixel translations, like DANDI 001278 / ome-zarr-tools."""
    level0 = np.zeros((37, 35, 35), np.uint8)  # odd sizes -> ceil-halved levels (19,18,18),(10,9,9)
    shapes = [(37, 35, 35), (19, 18, 18), (10, 9, 9)]
    s0 = 7.888
    scales = [[s0 * a / b for a, b in zip(shapes[0], shp, strict=True)] for shp in shapes]
    translations = [[(sn - s0) / 2 for sn in sc] for sc in scales]
    path = write_ome_zarr(
        tmp_path / "dandi.ome.zarr", level0, n_levels=3, scales=scales, translations=translations
    )
    return OmeZarrReader(path)


def test_write_matches_oracle_half_pixel_non_exact(tmp_path, monkeypatch):
    from ome_zarr_masker.io import writer

    monkeypatch.setattr(writer, "DEFAULT_CHUNKS", (4, 4, 4))
    monkeypatch.setattr(writer, "DEFAULT_MAX_SHARD", 8)  # several shards per level
    reader = _dandi_style_reader(tmp_path)
    mask = _blob(reader.level_shape(2), seed=1)
    out = write_mask(tmp_path / "out.ome.zarr", mask, 2, reader, {})
    _assert_matches_oracle(out, reader, 2, mask)
    validate_ome_zarr(out)
    assert_ome_zarr_models_valid(out)


# -- failure safety (FR-008, C-OUT-8) ----------------------------------------------------------


def _failing_after(n, real):
    import threading

    calls = {"n": 0}
    lock = threading.Lock()

    def wrapped(*args, **kwargs):
        with lock:
            calls["n"] += 1
            k = calls["n"]
        if k == n:
            raise RuntimeError("injected shard failure")
        return real(*args, **kwargs)

    return wrapped


def test_mid_write_failure_leaves_nothing_behind(tmp_path, monkeypatch):
    from ome_zarr_masker.io import writer

    monkeypatch.setattr(writer, "DEFAULT_CHUNKS", (4, 4, 4))
    monkeypatch.setattr(writer, "DEFAULT_MAX_SHARD", 4)
    reader = _reader(tmp_path)
    mask = np.ones(reader.level_shape(0), np.uint8)
    monkeypatch.setattr(writer, "_write_shard", _failing_after(3, writer._write_shard))
    out = tmp_path / "out.ome.zarr"
    with pytest.raises(RuntimeError, match="injected"):
        write_mask(out, mask, 0, reader, {}, workers=2)
    assert not out.exists()
    assert not out.with_name(out.name + ".tmp").exists()


def test_failed_overwrite_keeps_previous_output(tmp_path, monkeypatch):
    from ome_zarr_masker.io import writer

    reader = _reader(tmp_path)
    out = tmp_path / "out.ome.zarr"
    first = np.zeros(reader.level_shape(0), np.uint8)
    first[1:3, 2:5, 2:5] = 1
    write_mask(out, first, 0, reader, {"run": "first"})
    before = OmeZarrReader(out).read_level(0).copy()

    monkeypatch.setattr(writer, "DEFAULT_CHUNKS", (4, 4, 4))
    monkeypatch.setattr(writer, "DEFAULT_MAX_SHARD", 4)
    monkeypatch.setattr(writer, "_write_shard", _failing_after(3, writer._write_shard))
    with pytest.raises(RuntimeError, match="injected"):
        write_mask(
            out, np.ones_like(first), 0, reader, {"run": "second"}, overwrite=True, workers=2
        )
    assert np.array_equal(OmeZarrReader(out).read_level(0), before)
    assert '"first"' in (out / "run_record.json").read_text()
    assert not out.with_name(out.name + ".tmp").exists()


# -- storage: compression, empty shards, partial reads (US2: FR-003/004/005, SC-002/004) ----------


def _level_codecs(out, level):
    import json

    meta = json.loads((out / str(level) / "zarr.json").read_text())
    return meta, meta["codecs"][0]


def test_levels_are_sharded_blosc_fill_zero(tmp_path):
    reader = _reader(tmp_path)
    mask = _blob(reader.level_shape(0))
    out = write_mask(tmp_path / "out.ome.zarr", mask, 0, reader, {})
    for i in range(reader.n_levels):
        meta, sharding = _level_codecs(out, i)
        assert meta["fill_value"] == 0
        assert meta["data_type"] == "uint8"
        assert sharding["name"] == "sharding_indexed"
        inner = {c["name"]: c.get("configuration", {}) for c in sharding["configuration"]["codecs"]}
        assert (inner["blosc"]["cname"], inner["blosc"]["clevel"], inner["blosc"]["shuffle"]) == (
            "zstd",
            3,
            "bitshuffle",
        )


def test_all_background_mask_stores_no_data(tmp_path):
    reader = _reader(tmp_path)
    out = write_mask(
        tmp_path / "out.ome.zarr", np.zeros(reader.level_shape(0), np.uint8), 0, reader, {}
    )
    for i in range(reader.n_levels):
        assert not (out / str(i) / "c").exists() or not any((out / str(i) / "c").rglob("*"))
    assert_ome_zarr_models_valid(out)


def test_mostly_background_mask_is_small_on_disk(tmp_path):
    vol = np.zeros((128, 256, 256), np.uint8)
    reader = OmeZarrReader(write_ome_zarr(tmp_path / "in.ome.zarr", vol, n_levels=3))
    mask = np.zeros(reader.level_shape(0), np.uint8)
    mask[40:90, 60:200, 70:190] = 1  # ~12% foreground, compact organ-like block
    out = write_mask(tmp_path / "out.ome.zarr", mask, 0, reader, {})
    stored = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    uncompressed = sum(int(np.prod(reader.level_shape(i))) for i in range(reader.n_levels))
    assert stored < 0.05 * uncompressed, f"{stored} bytes vs {uncompressed} uncompressed"
    assert_ome_zarr_models_valid(out)


def test_reading_one_shard_touches_one_shard_file(tmp_path, monkeypatch):
    import zarr

    from ome_zarr_masker.io import writer

    monkeypatch.setattr(writer, "DEFAULT_CHUNKS", (4, 4, 4))
    monkeypatch.setattr(writer, "DEFAULT_MAX_SHARD", 8)
    reader = _reader(tmp_path, n_levels=1)  # (8, 16, 16) -> 1 x 2 x 2 shards of 8^3
    mask = _blob(reader.level_shape(0), seed=3)
    out = write_mask(tmp_path / "out.ome.zarr", mask, 0, reader, {})

    requested: list[str] = []

    class RecordingStore(zarr.storage.LocalStore):
        async def get(self, key, prototype, byte_range=None):
            requested.append(key)
            return await super().get(key, prototype, byte_range)

    arr = zarr.open_array(store=RecordingStore(str(out)), path="0", mode="r")
    assert arr.shards == (8, 8, 8)
    block = arr[0:8, 0:8, 0:8]
    assert np.array_equal(block, mask[0:8, 0:8, 0:8])
    data_keys = {k for k in requested if "/c/" in k}
    assert data_keys == {"0/c/0/0/0"}, data_keys
