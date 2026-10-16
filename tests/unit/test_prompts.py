"""Unit tests for the SAM2-compatible prompt model (T006)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from organ_masker_lite.prompts.model import (
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


# -- PromptSet.resolved_for_shape (feature 008-level-agnostic-prompts) --------------------------


def test_resolved_for_shape_identity_when_shapes_equal():
    ps = PromptSet(
        [Prompt(frame_index=2, point_coords=[[3, 4]], point_labels=[1], box=[1, 1, 5, 5])],
        level=0,
    )
    out = ps.resolved_for_shape((4, 8, 8), (4, 8, 8), axis_index=0)
    assert out is ps


def test_resolved_for_shape_isotropic_conversion():
    ps = PromptSet(
        [Prompt(frame_index=1, point_coords=[[2, 3]], point_labels=[1], box=[1, 1, 3, 3])]
    )
    out = ps.resolved_for_shape((4, 8, 8), (8, 16, 16), axis_index=0)
    p = out.prompts[0]
    assert p.frame_index == 2
    assert p.point_coords.tolist() == [[4, 6]]
    assert p.box.tolist() == [2, 2, 6, 6]


def test_resolved_for_shape_sweep_axis_ratio_independent_of_in_plane_ratio():
    """The sweep axis (frame_index) may scale by a different factor than the in-plane axes."""
    ps = PromptSet([Prompt(frame_index=1, point_coords=[[2, 3]], point_labels=[1])])
    out = ps.resolved_for_shape((4, 8, 8), (8, 8, 8), axis_index=0)
    p = out.prompts[0]
    assert p.frame_index == 2  # sweep axis (z) doubled
    assert p.point_coords.tolist() == [[2, 3]]  # in-plane axes unchanged


def test_resolved_for_shape_height_and_width_scale_independently():
    """x (width) and y (height) may scale by different factors from each other too."""
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[2, 3]], point_labels=[1])])
    out = ps.resolved_for_shape((4, 8, 8), (4, 16, 24), axis_index=0)
    # height (axis 1) ratio 16/8=2 -> y: 3*2=6; width (axis 2) ratio 24/8=3 -> x: 2*3=6
    assert out.prompts[0].point_coords.tolist() == [[6, 6]]


def test_resolved_for_shape_rounds_to_nearest_pixel():
    ps = PromptSet([Prompt(frame_index=0, point_coords=[[3, 0]], point_labels=[1])])
    out = ps.resolved_for_shape((4, 8, 8), (4, 8, 10), axis_index=0)
    # width ratio 10/8=1.25; 3*1.25=3.75 rounds to 4, not floors to 3
    assert out.prompts[0].point_coords.tolist() == [[4, 0]]


def test_resolved_for_shape_preserves_level_attribute():
    ps = PromptSet([Prompt(frame_index=1, point_coords=[[2, 3]], point_labels=[1])], level=0)
    out = ps.resolved_for_shape((4, 8, 8), (8, 16, 16), axis_index=0)
    assert out.level == 0


def test_resolved_for_shape_meets_performance_budget():
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
    ps.resolved_for_shape((4, 8, 8), (8, 16, 16), axis_index=0)
    elapsed = time.perf_counter() - start
    assert elapsed < 4e-3, f"resolved_for_shape took {elapsed * 1000:.3f} ms for 500 prompts"
