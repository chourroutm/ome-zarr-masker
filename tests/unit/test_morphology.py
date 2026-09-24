"""Unit tests for postprocess_mask's --invert step and its ordering (FR-003, FR-004).

Fast and GPU-free: exercises postprocess_mask() directly on synthetic arrays, unlike the
real_backend-gated end-to-end coverage in tests/integration/test_us5_postprocess.py.
"""

from __future__ import annotations

import numpy as np

from organ_masker_lite.config import PostProcessConfig
from organ_masker_lite.postprocess.morphology import postprocess_mask


def _cuboid_mask() -> np.ndarray:
    mask = np.zeros((8, 16, 16), dtype=bool)
    mask[2:6, 4:12, 4:12] = True
    return mask


def test_invert_is_exact_complement_of_non_inverted():
    mask = _cuboid_mask()
    normal = postprocess_mask(mask, PostProcessConfig(fill_holes=False))
    inverted = postprocess_mask(mask, PostProcessConfig(fill_holes=False, invert=True))
    assert np.array_equal(inverted, ~normal)


def test_invert_applies_after_dilate_erode_fill_holes():
    mask = _cuboid_mask()
    shaped = postprocess_mask(
        mask, PostProcessConfig(fill_holes=True, dilation_radius=2, erosion_radius=1)
    )
    shaped_then_inverted = postprocess_mask(
        mask,
        PostProcessConfig(fill_holes=True, dilation_radius=2, erosion_radius=1, invert=True),
    )
    # Complementing the inverted result must recover the organ-shaped (non-inverted) mask exactly
    # -- proves dilate/erode/fill-holes acted on the organ region, not the inverted background.
    assert np.array_equal(~shaped_then_inverted, shaped)


def test_invert_all_false_becomes_all_true():
    mask = np.zeros((4, 4, 4), dtype=bool)
    out = postprocess_mask(mask, PostProcessConfig(fill_holes=False, invert=True))
    assert out.all()


def test_invert_all_true_becomes_all_false():
    mask = np.ones((4, 4, 4), dtype=bool)
    out = postprocess_mask(mask, PostProcessConfig(fill_holes=False, invert=True))
    assert not out.any()
