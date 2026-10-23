"""Ordered post-processing steps against whole-volume references (feature 011, T006/T016).

Covers contracts/postprocess-notation.md C-PP-1/C-PP-2 and research R3/R4: every morphological step
equals a direct computation with an explicit ellipsoid structure over the whole volume, whatever
the slab size, thread count or algorithm (structure vs distance transform).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import ndimage

from ome_zarr_masker.postprocess.morphology import STRUCTURE_MAX_VOXELS, apply_steps
from ome_zarr_masker.postprocess.steps import ResolvedStep, parse_steps, resolve_steps

ISO = (1.0, 1.0, 1.0)
NO_UNITS = (None, None, None)


def _resolved(text: str, scale=ISO, units=NO_UNITS) -> tuple[ResolvedStep, ...]:
    return resolve_steps(parse_steps(text).steps, scale, units)


def _ellipsoid(radius_voxels, sampling) -> np.ndarray:
    """Reference structure: offsets whose sampled distance is within the radius."""
    r = radius_voxels[0] * sampling[0]
    ext = [int(math.floor(rv)) for rv in radius_voxels]
    grids = np.meshgrid(*[np.arange(-e, e + 1) for e in ext], indexing="ij")
    dist = np.sqrt(sum((g * s) ** 2 for g, s in zip(grids, sampling, strict=True)))
    return dist <= r


def _ref_dilate(m, rs: ResolvedStep):
    return ndimage.binary_dilation(m, structure=_ellipsoid(rs.radius_voxels, rs.sampling))


def _ref_erode(m, rs: ResolvedStep):
    return ndimage.binary_erosion(
        m, structure=_ellipsoid(rs.radius_voxels, rs.sampling), border_value=0
    )


def _ref_close(m, rs: ResolvedStep):
    """Closing as if the volume continued with background: pad, close, crop."""
    p = [int(math.ceil(r)) for r in rs.radius_voxels]
    padded = np.pad(m, [(q, q) for q in p])
    closed = _ref_erode(_ref_dilate(padded, rs), rs)
    return closed[tuple(slice(q, q + n) for q, n in zip(p, m.shape, strict=True))]


def _ref_open(m, rs: ResolvedStep):
    return _ref_dilate(_ref_erode(m, rs), rs)


REFERENCES = {
    "dilate": _ref_dilate,
    "margin": _ref_dilate,
    "erode": _ref_erode,
    "close": _ref_close,
    "open": _ref_open,
}


def _random_mask(shape=(20, 24, 22), seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = ndimage.gaussian_filter(rng.random(shape), 2.0)
    return noise > np.quantile(noise, 0.6)


def _sphere(shape=(40, 40, 40), radius=12.0, center=None) -> np.ndarray:
    center = center or tuple(n / 2 for n in shape)
    grids = np.ogrid[tuple(slice(0, n) for n in shape)]
    return sum((g - c) ** 2 for g, c in zip(grids, center, strict=True)) < radius**2


# -- each step vs reference (C-PP-2) -----------------------------------------------------------


@pytest.mark.parametrize("op", ["dilate", "margin", "erode", "close", "open"])
@pytest.mark.parametrize("radius", ["1", "2.5", "3", "6"])
def test_morphology_matches_reference(op, radius):
    mask = _random_mask()
    (rs,) = _resolved(f"{op}:{radius}")
    expected = REFERENCES[op](mask, rs)
    np.testing.assert_array_equal(apply_steps(mask, (rs,)), expected)


@pytest.mark.parametrize("workers", [1, 4])
@pytest.mark.parametrize("slab", [1, 7, None])
@pytest.mark.parametrize("op", ["dilate", "erode", "close", "open"])
def test_slabs_and_threads_do_not_change_the_result(op, workers, slab):
    mask = _random_mask(seed=1)
    for radius in ("2", "6"):  # structure path and distance-transform path
        rs = _resolved(f"{op}:{radius}")
        whole = apply_steps(mask, rs, workers=1, slab=mask.shape[0])
        np.testing.assert_array_equal(apply_steps(mask, rs, workers=workers, slab=slab), whole)


def test_both_algorithms_are_exercised():
    """Radii 2 and 6 fall on either side of the structure / distance-transform switch."""
    small = _ellipsoid((2.0,) * 3, ISO).sum()
    large = _ellipsoid((6.0,) * 3, ISO).sum()
    assert small <= STRUCTURE_MAX_VOXELS < large


def test_close_keeps_a_sample_touching_the_edge_and_open_adds_nothing():
    mask = np.zeros((16, 20, 20), bool)
    mask[:, 4:16, 4:16] = True  # touches the first and last planes
    mask[8, 6:14, 6:14] = False  # a gap plane inside
    for radius in ("2", "6"):
        closed = apply_steps(mask, _resolved(f"close:{radius}"))
        assert not (mask & ~closed).any()  # never removes
        assert closed[8, 6:14, 6:14].all()  # the gap is closed
        opened = apply_steps(mask, _resolved(f"open:{radius}"))
        assert not (opened & ~mask).any()  # never adds


def test_erode_treats_outside_as_background():
    mask = np.ones((10, 10, 10), bool)
    eroded = apply_steps(mask, _resolved("erode:2"))
    assert eroded[2:-2, 2:-2, 2:-2].all() and eroded.sum() == 6**3


def test_fill_matches_binary_fill_holes():
    mask = _sphere()
    mask[18:22, 18:22, 18:22] = False  # interior cavity
    np.testing.assert_array_equal(
        apply_steps(mask, _resolved("fill")), ndimage.binary_fill_holes(mask)
    )


def test_largest_uses_26_connectivity_and_scan_order_ties():
    mask = np.zeros((10, 10, 10), bool)
    mask[1:4, 1:4, 1:4] = True  # 27 voxels
    mask[4, 4, 4] = True  # touches the cube by a corner only: same component (26-connected)
    mask[6:9, 6:9, 6:8] = True  # 18 voxels, separate
    out = apply_steps(mask, _resolved("largest"))
    assert out[4, 4, 4] and out[1:4, 1:4, 1:4].all() and not out[6:9, 6:9, 6:8].any()

    tie = np.zeros((10, 10, 10), bool)
    tie[0:2, 0:2, 0:2] = True
    tie[7:9, 7:9, 7:9] = True
    out = apply_steps(tie, _resolved("largest"))
    assert out[0:2, 0:2, 0:2].all() and not out[7:9, 7:9, 7:9].any()


def test_largest_of_empty_is_empty_and_invert_complements():
    empty = np.zeros((5, 6, 7), bool)
    assert not apply_steps(empty, _resolved("largest")).any()
    assert apply_steps(empty, _resolved("invert")).all()
    mask = _random_mask()
    np.testing.assert_array_equal(apply_steps(mask, _resolved("invert")), ~mask)


def test_steps_after_invert_act_on_the_inverted_mask():
    mask = _random_mask()
    got = apply_steps(mask, _resolved("invert,largest"))
    expected = apply_steps(~mask, _resolved("largest"))
    np.testing.assert_array_equal(got, expected)


def test_order_matters_and_repeats_apply_again():
    # a big blob and a small blob 3 voxels apart: closing first merges them, so largest keeps both
    mask = np.zeros((12, 30, 12), bool)
    mask[3:9, 2:14, 3:9] = True
    mask[4:8, 17:21, 4:8] = True
    a = apply_steps(mask, _resolved("close:3,largest"))
    b = apply_steps(mask, _resolved("largest,close:3"))
    assert a[4:8, 17:21, 4:8].all() and not b[4:8, 17:21, 4:8].any()

    once = apply_steps(mask, _resolved("dilate:1"))
    twice = apply_steps(mask, _resolved("dilate:1,dilate:1"))
    np.testing.assert_array_equal(twice, apply_steps(once, _resolved("dilate:1")))


def test_users_sequence_fixes_gap_hole_and_fragment():
    """SC-001: close, fill, largest, margin -- the feedback's workaround in one sequence."""
    raw = _sphere((48, 48, 48), 14.0)
    raw[24, :, :] = False  # a sweep dropout: one missing plane
    raw[20:23, 20:23, 20:23] = False  # an interior hole
    raw[2:4, 2:4, 2:4] = True  # a detached fragment
    out = apply_steps(raw, _resolved("close:3,fill,largest,margin:3"))

    target = _sphere((48, 48, 48), 14.0)
    assert out[24][target[24]].all()  # gap plane closed
    assert out[20:23, 20:23, 20:23].all()  # hole filled
    assert not out[2:4, 2:4, 2:4].any()  # fragment dropped
    rings = ndimage.binary_dilation(target, iterations=1) & ~target
    assert out[rings].all()  # the margin was added

    close, margin = _resolved("close:3")[0], _resolved("margin:3")[0]
    step = ndimage.binary_fill_holes(_ref_close(raw, close))
    labels, _ = ndimage.label(step, structure=np.ones((3, 3, 3)))
    step = labels == 1 + int(np.argmax(np.bincount(labels.ravel())[1:]))
    np.testing.assert_array_equal(out, _ref_dilate(step, margin))


def test_no_steps_returns_a_copy():
    mask = _random_mask()
    out = apply_steps(mask, ())
    np.testing.assert_array_equal(out, mask)
    assert out is not mask
