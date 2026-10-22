"""Unit tests for the shared physical nearest-pixel mapping between pyramid levels."""

from __future__ import annotations

import numpy as np

from organ_masker_lite.geometry import nearest_index


def test_identity_when_transforms_match():
    out = nearest_index([0, 3, 7], 2.0, 1.5, 2.0, 1.5)
    assert out.tolist() == [0, 3, 7]


def test_translation_free_downsample_by_two_ties_go_to_lower_index():
    # voxel centres 0,1,2,3 at scale 1 land on 0, 0.5, 1, 1.5 at scale 2: ties resolve downward
    assert nearest_index([0, 1, 2, 3], 1.0, 0.0, 2.0, 0.0).tolist() == [0, 0, 1, 1]


def test_translation_free_upsample_by_two():
    assert nearest_index([0, 1, 4], 2.0, 0.0, 1.0, 0.0).tolist() == [0, 2, 8]


def test_half_pixel_translation_matches_brute_force_nearest_centre():
    # DANDI 001278 level 3 -> level 0 (z axis), scale/translation from its multiscales metadata
    s3, t3, s0, t0 = 63.0872348565356, 27.599617428267802, 7.888, 0.0
    src = np.arange(0, 941, 7)
    got = nearest_index(src, s3, t3, s0, t0)
    centres0 = np.arange(7526) * s0 + t0
    for i, g in zip(src, got, strict=True):
        p = i * s3 + t3
        d = np.abs(centres0 - p)
        expected = int(np.flatnonzero(d <= d.min() + 1e-9)[0])  # nearest, ties -> lower
        assert g == expected


def test_result_is_int64_and_unclipped():
    out = nearest_index(np.array([0.0]), 1.0, 0.0, 1.0, 100.0)
    assert out.dtype == np.int64
    assert out.tolist() == [-100]
