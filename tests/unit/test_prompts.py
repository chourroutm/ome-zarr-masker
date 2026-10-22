"""Unit tests for the SAM2-compatible prompt model (T006)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from ome_zarr_masker.prompts.model import (
    Prompt,
    PromptError,
    PromptSet,
    load_prompt_file,
)


def test_point_coords_and_labels_must_match():
    with pytest.raises(PromptError):
        Prompt(frame_index=0, point_coords=[[1, 2], [3, 4]], point_labels=[1])


def test_labels_must_be_zero_or_one():
    with pytest.raises(PromptError):
        Prompt(frame_index=0, point_coords=[[1, 2]], point_labels=[2])


def test_positive_and_negative_coords_split():
    p = Prompt(frame_index=0, point_coords=[[1, 1], [2, 2]], point_labels=[1, 0])
    assert p.positive_coords.tolist() == [[1, 1]]
    assert p.negative_coords.tolist() == [[2, 2]]


def test_validate_requires_a_positive_prompt():
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[1, 1]], point_labels=[0])])
    with pytest.raises(PromptError):
        ps.validate(level_shape=(4, 8, 8), axis_index=0)


def test_validate_rejects_out_of_bounds_point():
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[99, 1]], point_labels=[1])])
    with pytest.raises(PromptError):
        ps.validate(level_shape=(4, 8, 8), axis_index=0)


def test_validate_rejects_out_of_range_frame():
    ps = PromptSet([Prompt(frame_index=99, point_coords=[[1, 1]], point_labels=[1])])
    with pytest.raises(PromptError):
        ps.validate(level_shape=(4, 8, 8), axis_index=0)


def test_validate_accepts_in_bounds_box():
    ps = PromptSet(
        [
            Prompt(
                frame_index=0,
                point_coords=np.empty((0, 2)),
                point_labels=np.empty((0,), int),
                box=[1, 1, 5, 5],
            )
        ]
    )
    ps.validate(level_shape=(4, 8, 8), axis_index=0)  # no raise


def test_load_prompt_file_single_point(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(
        json.dumps(
            {
                "level": 0,
                "objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}],
            }
        )
    )
    ps = load_prompt_file(f)
    assert len(ps.prompts) == 1
    assert ps.prompts[0].frame_index == 4
    assert ps.has_positive()


def test_load_prompt_file_box(tmp_path):
    f = tmp_path / "b.json"
    f.write_text(
        json.dumps({"level": 0, "objects": [{"box": {"frame": 4, "xyxy": [3, 3, 13, 13]}}]})
    )
    ps = load_prompt_file(f)
    assert ps.prompts[0].box.tolist() == [3, 3, 13, 13]
    assert ps.has_positive()


def test_load_prompt_file_requires_level_key(tmp_path):
    """FR-007: the pre-feature-008 format (no top-level "level") is rejected, never guessed at."""
    f = tmp_path / "old.json"
    f.write_text(
        json.dumps({"objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}]})
    )
    with pytest.raises(PromptError):
        load_prompt_file(f)


def test_load_prompt_file_parses_level(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(
        json.dumps(
            {
                "level": 3,
                "objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}],
            }
        )
    )
    ps = load_prompt_file(f)
    assert ps.level == 3


# -- PromptSet.level (feature 008-level-agnostic-prompts) --------------------------------------


def test_prompt_set_level_defaults_to_none():
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[1, 1]], point_labels=[1])])
    assert ps.level is None


def test_prompt_set_level_is_settable():
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[1, 1]], point_labels=[1])], level=3)
    assert ps.level == 3


def test_to_record_wraps_level_and_objects():
    ps = PromptSet([Prompt(frame_index=4, point_coords=[[8, 8]], point_labels=[1])], level=2)
    record = ps.to_record()
    assert record["level"] == 2
    assert record["objects"][0]["frame_index"] == 4


def test_to_record_level_is_none_when_unset():
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[1, 1]], point_labels=[1])])
    assert ps.to_record()["level"] is None


# -- PromptSet.resolved_between: physical mapping between levels -------------------------------
# A level's geometry is (scale, translation) per (z, y, x) axis, as in its OME-Zarr metadata.


def _geo(scale, translation=(0.0, 0.0, 0.0)):
    return (tuple(float(s) for s in scale), tuple(float(t) for t in translation))


def test_resolved_between_identity_when_geometry_matches():
    ps = PromptSet(
        [Prompt(frame_index=2, point_coords=[[3, 4]], point_labels=[1], box=[1, 1, 5, 5])],
        level=0,
    )
    g = _geo((2, 2, 2), (0.5, 0.5, 0.5))
    assert ps.resolved_between(g, g, axis_index=0) is ps


def test_resolved_between_isotropic_upsample():
    ps = PromptSet(
        [Prompt(frame_index=1, point_coords=[[2, 3]], point_labels=[1], box=[1, 1, 3, 3])]
    )
    out = ps.resolved_between(_geo((2, 2, 2)), _geo((1, 1, 1)), axis_index=0)
    p = out.prompts[0]
    assert p.frame_index == 2
    assert p.point_coords.tolist() == [[4, 6]]
    assert p.box.tolist() == [2, 2, 6, 6]


def test_resolved_between_sweep_axis_independent_of_in_plane_axes():
    """The sweep axis (frame_index) may scale by a different factor than the in-plane axes."""
    ps = PromptSet([Prompt(frame_index=1, point_coords=[[2, 3]], point_labels=[1])])
    out = ps.resolved_between(_geo((2, 1, 1)), _geo((1, 1, 1)), axis_index=0)
    p = out.prompts[0]
    assert p.frame_index == 2  # sweep axis (z) doubled
    assert p.point_coords.tolist() == [[2, 3]]  # in-plane axes unchanged


def test_resolved_between_height_and_width_scale_independently():
    """x (width, axis 2) and y (height, axis 1) may scale by different factors too."""
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[2, 3]], point_labels=[1])])
    out = ps.resolved_between(_geo((1, 2, 3)), _geo((1, 1, 1)), axis_index=0)
    # y: 3 * 2 = 6; x: 2 * 3 = 6
    assert out.prompts[0].point_coords.tolist() == [[6, 6]]


def test_resolved_between_rounds_to_nearest_pixel():
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[3, 0]], point_labels=[1])])
    out = ps.resolved_between(_geo((1, 1, 1.25)), _geo((1, 1, 1)), axis_index=0)
    # x: 3 * 1.25 = 3.75 rounds to 4, not floors to 3
    assert out.prompts[0].point_coords.tolist() == [[4, 0]]


def test_resolved_between_exact_tie_goes_to_lower_index():
    """Same rule as the mask writer (feature 009): an exact tie picks the lower pixel. The last
    column (x=15) of a 16-wide level lands on 7.5 at half resolution and stays in bounds (7)."""
    ps = PromptSet([Prompt(frame_index=4, point_coords=[[15, 15]], point_labels=[1])])
    out = ps.resolved_between(_geo((1, 1, 1)), _geo((2, 2, 2)), axis_index=0)
    p = out.prompts[0]
    assert p.frame_index == 2
    assert p.point_coords.tolist() == [[7, 7]]
    out.validate(level_shape=(4, 8, 8), axis_index=0)  # no raise


def test_resolved_between_uses_half_pixel_translations():
    """DANDI-style pyramid: translation_N = (scale_N - scale_0) / 2. A level-1 voxel centre sits
    between two level-0 centres, so it maps to the lower one; a level-0 centre maps into the level-1
    voxel that contains it."""
    lvl0 = _geo((1, 1, 1), (0, 0, 0))
    lvl1 = _geo((2, 2, 2), (0.5, 0.5, 0.5))
    ps = PromptSet([Prompt(frame_index=3, point_coords=[[3, 5]], point_labels=[1])])
    up = ps.resolved_between(lvl1, lvl0, axis_index=0).prompts[0]
    assert up.frame_index == 6  # 3*2 + 0.5 = 6.5 -> tie -> 6
    assert up.point_coords.tolist() == [[6, 10]]
    down = ps.resolved_between(lvl0, lvl1, axis_index=0).prompts[0]
    assert down.frame_index == 1  # (3 - 0.5) / 2 = 1.25 -> 1
    assert down.point_coords.tolist() == [[1, 2]]  # x: 1.25 -> 1; y: (5 - 0.5)/2 = 2.25 -> 2


def test_resolved_between_out_of_bounds_result_still_fails_validation():
    """Conversion never clamps: if metadata maps a point outside the run level, validate() rejects
    it (spec FR-005)."""
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[1, 1]], point_labels=[1])])
    out = ps.resolved_between(_geo((1, 1, 1)), _geo((1, 1, 1), (0, 0, -100)), axis_index=0)
    assert out.prompts[0].point_coords.tolist() == [[101, 1]]
    with pytest.raises(PromptError):
        out.validate(level_shape=(4, 8, 8), axis_index=0)


def test_resolved_between_preserves_level_attribute():
    ps = PromptSet([Prompt(frame_index=1, point_coords=[[2, 3]], point_labels=[1])], level=0)
    out = ps.resolved_between(_geo((2, 2, 2)), _geo((1, 1, 1)), axis_index=0)
    assert out.level == 0


def test_resolved_between_meets_performance_budget():
    """plan.md's declared budget: < 4 ms for 500 prompts (a generous ceiling for a thorough
    multi-frame annotation; Constitution Principle IV). Also guards against regressing to a
    per-prompt reconstruction that re-validates through Prompt's full __init__/__post_init__,
    which measured ~15x over this budget at this scale before the ``Prompt.__new__`` bypass.
    """
    import time

    ps = PromptSet(
        [
            Prompt(frame_index=i % 4, point_coords=[[i % 8, i % 8]], point_labels=[1])
            for i in range(500)
        ]
    )
    start = time.perf_counter()
    ps.resolved_between(_geo((2, 2, 2)), _geo((1, 1, 1)), axis_index=0)
    elapsed = time.perf_counter() - start
    assert elapsed < 4e-3, f"resolved_between took {elapsed * 1000:.3f} ms for 500 prompts"
