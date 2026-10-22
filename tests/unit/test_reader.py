"""Unit tests for the OME-Zarr reader (T009)."""

from __future__ import annotations

import numpy as np
import pytest

from organ_masker_lite.config import COARSEST_LEVEL
from organ_masker_lite.io.reader import OmeZarrReader, ReaderError

from ..conftest import write_ome_zarr


def _make(tmp_path, n_levels=3):
    vol = np.zeros((16, 16, 16), np.uint8)
    vol[4:12, 4:12, 4:12] = 200
    return write_ome_zarr(tmp_path / "in.ome.zarr", vol, n_levels=n_levels)


def test_reads_levels_and_axes(tmp_path):
    r = OmeZarrReader(_make(tmp_path, n_levels=3))
    assert r.n_levels == 3
    assert r.axes == ["z", "y", "x"]
    assert r.level_shape(0) == (16, 16, 16)
    assert r.level_shape(2) == (4, 4, 4)


def test_default_level_is_coarsest(tmp_path):
    r = OmeZarrReader(_make(tmp_path, n_levels=3))
    assert r.default_level() == 2
    assert r.resolve_level(COARSEST_LEVEL) == 2


def test_resolve_invalid_level_raises_with_available(tmp_path):
    r = OmeZarrReader(_make(tmp_path, n_levels=2))
    with pytest.raises(ReaderError) as exc:
        r.resolve_level(99)
    assert "available levels" in str(exc.value)


def test_read_level_returns_data(tmp_path):
    r = OmeZarrReader(_make(tmp_path, n_levels=2))
    vol = r.read_level(0)
    assert vol.shape == (16, 16, 16)
    assert vol.max() == 200


def test_level_transform_defaults_translation_to_zero(tmp_path):
    r = OmeZarrReader(_make(tmp_path, n_levels=3))  # fixture writes scales 2**i, no translations
    assert r.level_transform(0) == ((1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    assert r.level_transform(2) == ((4.0, 4.0, 4.0), (0.0, 0.0, 0.0))


def test_level_transform_reads_scale_and_translation(tmp_path):
    import zarr
    from ome_zarr_models.v05.axes import Axis
    from ome_zarr_models.v05.image import Image
    from pydantic_zarr.v3 import ArraySpec

    arrays = [np.zeros((8, 8, 8), np.uint8), np.zeros((4, 4, 4), np.uint8)]
    path = tmp_path / "t.ome.zarr"
    Image.new(
        array_specs=[ArraySpec.from_array(a, dimension_names=["z", "y", "x"]) for a in arrays],
        paths=["0", "1"],
        axes=[Axis(name=n, type="space") for n in ("z", "y", "x")],
        scales=[[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]],
        translations=[None, [0.5, 0.5, 0.5]],
    ).to_zarr(zarr.storage.LocalStore(str(path)), path="")
    r = OmeZarrReader(path)
    assert r.level_transform(1) == ((2.0, 2.0, 2.0), (0.5, 0.5, 0.5))
    assert r.level_transform(0) == ((1.0, 1.0, 1.0), (0.0, 0.0, 0.0))


def test_bad_path_raises(tmp_path):
    with pytest.raises(ReaderError):
        OmeZarrReader(tmp_path / "does-not-exist.ome.zarr")

