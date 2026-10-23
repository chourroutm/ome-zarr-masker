"""Apply an ordered sequence of post-processing steps to the run-level mask (feature 011).

Steps run in the order given, each on the result of the previous one (C-PP-1):

- ``dilate:R`` / ``margin:R`` add every voxel within distance R of the mask;
- ``erode:R`` removes every mask voxel within distance R of background, outside the volume
  counting as background;
- ``close:R`` is a dilation then an erosion computed as if the volume continued with background,
  so it never removes a mask voxel (a sample touching the volume edge is not eroded there);
- ``open:R`` is an erosion then a dilation, so it never adds a mask voxel;
- ``fill`` fills 3D holes, ``largest`` keeps the largest 26-connected component (the first in scan
  order on a tie), ``invert`` swaps mask and background.

Distances use the step's per-axis voxel radius, so the neighbourhood is an ellipsoid in voxels
(a ball in physical space) rather than iterations of a cross (research R3). Dilation and erosion
run slab by slab along the first axis on a thread pool, each slab with a halo as deep as the
radius, which bounds memory and doesn't change the result. Small neighbourhoods use an explicit
structure; above :data:`STRUCTURE_MAX_VOXELS` a Euclidean distance transform is used instead,
whose cost doesn't grow with the radius (research R4).
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy import ndimage

from .steps import ResolvedStep

#: Largest neighbourhood (in voxels) handled with an explicit structure; larger ones use a
#: distance transform (research R4: 2.7x faster at radius 3, 7x slower at radius 8).
STRUCTURE_MAX_VOXELS = 400
#: Planes per slab when the caller doesn't choose.
DEFAULT_SLAB = 64


def _ellipsoid(radius_voxels: Sequence[float], sampling: Sequence[float]) -> np.ndarray:
    """Offsets whose distance (in the radius's unit) is within the radius."""
    r = radius_voxels[0] * sampling[0]
    ext = [int(math.floor(rv)) for rv in radius_voxels]
    grids = np.meshgrid(*[np.arange(-e, e + 1) for e in ext], indexing="ij")
    dist = np.sqrt(sum((g * s) ** 2 for g, s in zip(grids, sampling, strict=True)))
    return dist <= r


def _slab_op(
    mask: np.ndarray, step: ResolvedStep, erode: bool, workers: int, slab: int
) -> np.ndarray:
    """Dilate (or erode) ``mask`` by ``step``'s radius, slab by slab along axis 0."""
    structure = _ellipsoid(step.radius_voxels, step.sampling)
    use_structure = int(structure.sum()) <= STRUCTURE_MAX_VOXELS
    r = step.radius_voxels[0] * step.sampling[0]
    halo = int(math.ceil(step.radius_voxels[0]))
    n = mask.shape[0]
    out = np.empty_like(mask)

    def work(start: int) -> None:
        stop = min(start + slab, n)
        lo, hi = max(0, start - halo), min(n, stop + halo)
        block = mask[lo:hi]
        if use_structure:
            if erode:
                res = ndimage.binary_erosion(block, structure=structure, border_value=0)
            else:
                res = ndimage.binary_dilation(block, structure=structure)
        elif erode:
            # one background voxel all round stands for "outside the volume is background"
            dist = ndimage.distance_transform_edt(np.pad(block, 1), sampling=step.sampling)
            res = dist[1:-1, 1:-1, 1:-1] > r
        elif not block.any():  # no mask voxel to measure from (the transform would fill all)
            res = block
        else:
            res = ndimage.distance_transform_edt(~block, sampling=step.sampling) <= r
        out[start:stop] = res[start - lo : start - lo + (stop - start)]

    starts = range(0, n, slab)
    if workers <= 1:
        for s in starts:
            work(s)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, starts))
    return out


def _close(mask: np.ndarray, step: ResolvedStep, workers: int, slab: int) -> np.ndarray:
    pad = [int(math.ceil(r)) for r in step.radius_voxels]
    padded = np.pad(mask, [(p, p) for p in pad])
    closed = _slab_op(_slab_op(padded, step, False, workers, slab), step, True, workers, slab)
    return closed[tuple(slice(p, p + n) for p, n in zip(pad, mask.shape, strict=True))]


def _largest(mask: np.ndarray) -> np.ndarray:
    labels, count = ndimage.label(mask, structure=np.ones((3,) * mask.ndim, dtype=bool))
    if count <= 1:
        return labels > 0
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return labels == int(np.argmax(sizes))  # labels follow scan order: first maximum wins


def apply_steps(
    mask: np.ndarray,
    steps: Sequence[ResolvedStep],
    *,
    workers: int | None = None,
    slab: int | None = None,
) -> np.ndarray:
    """Return ``mask`` (as bool) with ``steps`` applied in order; the input is never modified.

    ``workers`` threads (default: CPU count, at most 8) process ``slab`` planes each (default
    :data:`DEFAULT_SLAB`); neither changes the result.
    """
    out = np.array(mask, dtype=bool, copy=True)
    workers = workers if workers is not None else min(os.cpu_count() or 1, 8)
    slab = max(1, slab if slab is not None else DEFAULT_SLAB)
    for step in steps:
        op = step.op
        if op in ("dilate", "margin"):
            out = _slab_op(out, step, False, workers, slab)
        elif op == "erode":
            out = _slab_op(out, step, True, workers, slab)
        elif op == "close":
            out = _close(out, step, workers, slab)
        elif op == "open":
            out = _slab_op(_slab_op(out, step, True, workers, slab), step, False, workers, slab)
        elif op == "fill":
            out = ndimage.binary_fill_holes(out)
        elif op == "largest":
            out = _largest(out)
        elif op == "invert":
            out = ~out
        else:  # parse_steps only produces the ops above
            raise ValueError(f"unknown post-processing step {op!r}")
    return out


__all__ = ["STRUCTURE_MAX_VOXELS", "apply_steps"]
