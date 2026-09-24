"""Unit tests for the pure frame_range crop/remap and place-back helpers (research R3).

Fast and GPU-free: exercises the helpers directly on synthetic arrays/prompts, bypassing
compute_mask's real-SAM2 dependency entirely.
"""

from __future__ import annotations

import numpy as np

from organ_masker_lite.engine.pipeline import _crop_to_frame_range, _place_at_offset
from organ_masker_lite.prompts.model import Prompt, PromptSet


def _volume() -> np.ndarray:
    # (z, y, x) = (10, 4, 4), each z-slice filled with its own index for easy inspection
    vol = np.zeros((10, 4, 4), dtype=np.uint8)
    for z in range(10):
        vol[z] = z
    return vol


def test_crop_restricts_volume_to_frame_range_along_axis():
    volume = _volume()
    prompts = PromptSet([Prompt(frame_index=3, point_coords=[[1, 1]], point_labels=[1])])

    cropped, _, offset = _crop_to_frame_range(volume, prompts, (2, 5), axis_index=0)

    assert offset == 2
    assert cropped.shape == (4, 4, 4)
    assert np.array_equal(cropped[:, 0, 0], [2, 3, 4, 5])


def test_crop_remaps_in_range_prompt_frame_indices():
    prompts = PromptSet(
        [
            Prompt(frame_index=3, point_coords=[[1, 1]], point_labels=[1], obj_id=0),
            Prompt(frame_index=4, point_coords=[[2, 2]], point_labels=[0], obj_id=1),
        ]
    )
    _, remapped, offset = _crop_to_frame_range(_volume(), prompts, (2, 5), axis_index=0)

    assert offset == 2
    assert sorted(p.frame_index for p in remapped.prompts) == [1, 2]
    # obj_id and labels survive remapping unchanged
    by_obj = {p.obj_id: p for p in remapped.prompts}
    assert by_obj[0].frame_index == 1
    assert by_obj[1].frame_index == 2
    assert by_obj[1].point_labels.tolist() == [0]


def test_crop_drops_prompts_outside_the_range():
    prompts = PromptSet(
        [
            Prompt(frame_index=0, point_coords=[[1, 1]], point_labels=[1]),  # outside [2, 5]
            Prompt(frame_index=8, point_coords=[[1, 1]], point_labels=[1]),  # outside [2, 5]
            Prompt(frame_index=4, point_coords=[[1, 1]], point_labels=[1]),  # inside
        ]
    )
    _, remapped, _ = _crop_to_frame_range(_volume(), prompts, (2, 5), axis_index=0)

    assert len(remapped.prompts) == 1
    assert remapped.prompts[0].frame_index == 2


def test_place_at_offset_populates_only_the_cropped_range():
    cropped = np.ones((4, 4, 4), dtype=bool)
    full = _place_at_offset(cropped, offset=2, axis_index=0, full_shape=(10, 4, 4))

    assert full.shape == (10, 4, 4)
    assert full.dtype == bool
    assert full[:2].sum() == 0
    assert full[6:].sum() == 0
    assert full[2:6].all()
