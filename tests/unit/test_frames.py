"""Unit tests for frame normalisation and the memmap frame store (T012)."""

from __future__ import annotations

import numpy as np

from ome_zarr_masker.engine.frames import build_frame_stack, normalize_to_uint8


def test_normalize_spans_full_uint8_range():
    vol = np.array([[[0.0, 100.0]]])
    out = normalize_to_uint8(vol)
    assert out.dtype == np.uint8
    assert out.min() == 0 and out.max() == 255


def test_normalize_constant_volume_is_zero():
    out = normalize_to_uint8(np.full((2, 2, 2), 7.0))
    assert out.dtype == np.uint8
    assert (out == 0).all()


def test_build_frame_stack_shape_and_rgb(tmp_path):
    vol = np.zeros((5, 6, 7), np.uint8)
    vol[1:3, 1:4, 1:5] = 200
    frames = build_frame_stack(vol, tmp_path)
    assert frames.shape == (5, 6, 7, 3)
    assert frames.dtype == np.uint8
    # channels are replicated
    assert (frames[..., 0] == frames[..., 1]).all()
    assert frames.max() == 255
