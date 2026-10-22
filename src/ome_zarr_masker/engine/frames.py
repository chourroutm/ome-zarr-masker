"""Normalise volume slices into a uint8 RGB frame stack in an on-disk memmap (research R3)."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def normalize_to_uint8(volume: np.ndarray) -> np.ndarray:
    """Linearly normalise a volume to uint8 over its global min/max."""
    v = np.asarray(volume, dtype=np.float64)
    vmin = float(v.min()) if v.size else 0.0
    vmax = float(v.max()) if v.size else 0.0
    if vmax > vmin:
        scaled = (v - vmin) / (vmax - vmin) * 255.0
    else:
        scaled = np.zeros_like(v)
    return scaled.astype(np.uint8)


def build_frame_stack(volume_axis0: np.ndarray, workdir: str | Path) -> np.memmap:
    """Build a ``(T, H, W, 3)`` uint8 memmap of normalised RGB frames.

    ``volume_axis0`` is the volume with the sweep axis already moved to axis 0. Frames are written
    one slice at a time into the on-disk memmap, so peak RAM holds at most a single float slice
    rather than a float64 copy of the whole volume (Principle IV: depth-independent intermediates).
    Normalisation uses the global min/max, matching :func:`normalize_to_uint8`.
    """
    n_frames, height, width = volume_axis0.shape
    vmin = float(np.min(volume_axis0)) if volume_axis0.size else 0.0
    vmax = float(np.max(volume_axis0)) if volume_axis0.size else 0.0
    span = vmax - vmin

    path = Path(workdir) / "frames.dat"
    frames = np.memmap(path, dtype=np.uint8, mode="w+", shape=(n_frames, height, width, 3))
    for i in range(n_frames):
        if span > 0:
            scaled = (np.asarray(volume_axis0[i], dtype=np.float64) - vmin) / span * 255.0
            slice_u8 = scaled.astype(np.uint8)
        else:
            slice_u8 = np.zeros((height, width), dtype=np.uint8)
        frames[i, ..., :] = slice_u8[..., None]
    frames.flush()
    return frames
