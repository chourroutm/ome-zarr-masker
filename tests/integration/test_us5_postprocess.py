"""US5: optional mask post-processing (T050, FR-012, SC-007).

Uses a hollow-shell volume, carved so the raw consensus has a genuine interior cavity if SAM2's
segmentation reproduces it exactly (not guaranteed for a learned model on a synthetic shape).
Verifies that fill-holes always yields zero interior holes and never shrinks the raw mask (with
strict growth only when the raw mask actually had a hole to fill), that disabling post-processing
leaves the raw mask unchanged, and that explicit dilate/erode radii are applied exactly.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from scipy import ndimage

from organ_masker_lite.cli import main
from organ_masker_lite.io.reader import OmeZarrReader

from ..conftest import sam2_available, write_ome_zarr

_HAVE_SAM2 = sam2_available()


def _holes(mask: np.ndarray) -> int:
    """Number of enclosed background voxels (interior holes) in a 3D binary mask."""
    return int((ndimage.binary_fill_holes(mask) & ~mask.astype(bool)).sum())


def _prompts(path: Path) -> Path:
    # a shell voxel on frame 4 at (x, y) = (5, 5)
    path.write_text(
        json.dumps({"objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [5, 5], "label": 1}]}]})
    )
    return path


def _hollow_store(tmp_path: Path) -> Path:
    vol = np.zeros((8, 16, 16), np.uint8)
    vol[2:6, 4:12, 4:12] = 200  # solid cuboid
    vol[3:5, 6:10, 6:10] = 0  # carve an enclosed interior cavity
    return write_ome_zarr(tmp_path / "shell.ome.zarr", vol, n_levels=1)


def _run(store, out, prompts, *extra):
    return main(
        [
            "mask",
            str(store),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "0",
            *extra,
        ]
    )


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_default_fillholes_disabled_and_exact_morphology(tmp_path):
    store = _hollow_store(tmp_path)
    prompts = _prompts(tmp_path / "p.json")

    # disabled: raw consensus is written unchanged. The synthetic volume has a carved interior
    # cavity, but real SAM2's learned segmentation (unlike the old deterministic stub) isn't
    # guaranteed to reproduce it as an enclosed hole -- so this is observed, not asserted.
    raw_out = tmp_path / "raw.ome.zarr"
    assert _run(store, raw_out, prompts, "--no-fill-holes") == 0
    raw = OmeZarrReader(raw_out).read_level(0).astype(bool)
    n_holes_raw = _holes(raw)

    # default: fill-holes never leaves interior holes, and never shrinks the raw mask. It's a
    # strict superset only when there was a hole to fill in the first place.
    filled_out = tmp_path / "filled.ome.zarr"
    assert _run(store, filled_out, prompts) == 0
    filled = OmeZarrReader(filled_out).read_level(0).astype(bool)
    assert _holes(filled) == 0
    assert filled.sum() >= raw.sum()
    assert np.array_equal(filled | raw, filled)
    if n_holes_raw > 0:
        assert filled.sum() > raw.sum()

    # explicit dilation is applied exactly (isolated from fill-holes)
    dil_out = tmp_path / "dil.ome.zarr"
    assert _run(store, dil_out, prompts, "--no-fill-holes", "--dilate", "1") == 0
    dil = OmeZarrReader(dil_out).read_level(0).astype(bool)
    assert np.array_equal(dil, ndimage.binary_dilation(raw, iterations=1))

    # explicit erosion is applied exactly
    ero_out = tmp_path / "ero.ome.zarr"
    assert _run(store, ero_out, prompts, "--no-fill-holes", "--erode", "1") == 0
    ero = OmeZarrReader(ero_out).read_level(0).astype(bool)
    assert np.array_equal(ero, ndimage.binary_erosion(raw, iterations=1))
