"""Axis sweeps: present a volume as a frame stack and segment it via the backend.

Supports forward-only and forward-and-reverse propagation (FR-006), and deriving per-slice seeds
for a non-prompted axis from an already-computed 3D mask (FR-022).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..prompts.model import Prompt, PromptSet
from ..sam2 import Sam2Backend


def _check_shape(mask: np.ndarray, expected: tuple[int, ...]) -> np.ndarray:
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != expected:
        raise ValueError(f"backend returned mask of shape {mask.shape}, expected {expected}")
    return mask


def _reverse_prompts(prompts: PromptSet, n_frames: int) -> PromptSet:
    """Remap prompt frame indices for a reversed frame stack (``t -> n-1-t``)."""
    reversed_prompts = [
        Prompt(
            frame_index=n_frames - 1 - p.frame_index,
            point_coords=p.point_coords.copy(),
            point_labels=p.point_labels.copy(),
            box=None if p.box is None else p.box.copy(),
            obj_id=p.obj_id,
        )
        for p in prompts.prompts
    ]
    return PromptSet(reversed_prompts)


def run_sweep(
    volume: np.ndarray,
    axis_index: int,
    prompts: PromptSet,
    backend: Sam2Backend,
    workdir: str | Path,
    direction: str = "forward",
) -> np.ndarray:
    """Sweep ``volume`` along ``axis_index`` and return a 3D boolean mask in volume coordinates.

    The sweep axis is moved to axis 0 to form a ``(T, H, W)`` frame stack; the backend returns a
    ``(T, H, W)`` mask which is moved back. For ``forward_reverse`` the stack is also segmented in
    reverse (frames and prompt frames remapped) and the two passes are merged by union (FR-006).
    """
    from .frames import build_frame_stack

    if direction not in ("forward", "forward_reverse"):
        raise ValueError(f"unknown direction '{direction}'")
    workdir = Path(workdir)
    moved = np.moveaxis(volume, axis_index, 0)
    n_frames = moved.shape[0]

    fwd_dir = workdir / "fwd"
    fwd_dir.mkdir(parents=True, exist_ok=True)
    frames = build_frame_stack(moved, fwd_dir)
    mask = _check_shape(backend.segment_video(frames, prompts), moved.shape)

    if direction == "forward_reverse":
        rev_dir = workdir / "rev"
        rev_dir.mkdir(parents=True, exist_ok=True)
        rev_frames = build_frame_stack(moved[::-1], rev_dir)
        rev_prompts = _reverse_prompts(prompts, n_frames)
        rev_mask = _check_shape(backend.segment_video(rev_frames, rev_prompts), moved.shape)
        mask = mask | rev_mask[::-1]

    return np.moveaxis(mask, 0, axis_index)


def seeds_from_mask(seed_mask: np.ndarray, axis_index: int) -> PromptSet:
    """Derive per-slice positive-point prompts for ``axis_index`` from a 3D mask (FR-022).

    For every slice along ``axis_index`` that contains foreground, place one positive point on an
    actual foreground pixel of that slice (the median foreground location), expressed in the same
    ``(x, y)`` in-plane convention the backend consumes after the axis is moved to axis 0.
    """
    moved = np.moveaxis(np.asarray(seed_mask, dtype=bool), axis_index, 0)
    prompts: list[Prompt] = []
    for t in range(moved.shape[0]):
        fg = np.argwhere(moved[t])  # rows (axis 1), cols (axis 2)
        if fg.size == 0:
            continue
        row, col = fg[len(fg) // 2]
        prompts.append(
            Prompt(
                frame_index=t,
                point_coords=[[float(col), float(row)]],  # SAM convention: (x, y) = (col, row)
                point_labels=[1],
            )
        )
    return PromptSet(prompts)
