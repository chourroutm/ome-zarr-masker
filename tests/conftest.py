"""Shared test fixtures: a synthetic OME-Zarr v0.5 volume."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr
from ome_zarr_models.v05.axes import Axis
from ome_zarr_models.v05.image import Image
from pydantic_zarr.v3 import ArraySpec


def write_ome_zarr(path: Path, level0: np.ndarray, n_levels: int = 2) -> Path:
    """Write a minimal valid OME-Zarr v0.5 multiscale image (axes z, y, x)."""
    arrays = [level0]
    for _ in range(1, n_levels):
        arrays.append(arrays[-1][::2, ::2, ::2].copy())
    axes = [Axis(name=n, type="space") for n in ("z", "y", "x")]
    specs = [ArraySpec.from_array(a, dimension_names=["z", "y", "x"]) for a in arrays]
    image = Image.new(
        array_specs=specs,
        paths=[str(i) for i in range(n_levels)],
        axes=axes,
        scales=[[2.0**i] * 3 for i in range(n_levels)],
        translations=[None] * n_levels,
    )
    image.to_zarr(zarr.storage.LocalStore(str(path)), path="")
    for i, arr in enumerate(arrays):
        zarr.open_array(store=str(path), path=str(i), mode="r+")[:] = arr
    return path


@pytest.fixture
def single_blob_zarr(tmp_path):
    """A volume with one bright cuboid blob; returns (path, blob_center_xy, frame_index)."""
    vol = np.zeros((8, 16, 16), dtype=np.uint8)
    vol[2:6, 4:12, 4:12] = 200
    path = write_ome_zarr(tmp_path / "input.ome.zarr", vol)
    # center of the blob on frame z=4: (x, y) = (8, 8)
    return path, (8.0, 8.0), 4


@pytest.fixture
def two_blob_zarr(tmp_path):
    """A volume with two separate blobs; returns (path, blobA_xy, blobB_xy, frame_index)."""
    vol = np.zeros((8, 24, 24), dtype=np.uint8)
    vol[2:6, 3:9, 3:9] = 200  # blob A
    vol[2:6, 15:21, 15:21] = 200  # blob B (separate)
    path = write_ome_zarr(tmp_path / "two.ome.zarr", vol)
    return path, (6.0, 6.0), (18.0, 18.0), 4


@pytest.fixture(autouse=True)
def isolate_logs(tmp_path, monkeypatch):
    """Redirect per-invocation input logs (feature 002) to a temp dir, never the repo cwd."""
    monkeypatch.setenv("ORGAN_MASKER_LOG_DIR", str(tmp_path / "_logs"))


def sam2_available() -> bool:
    """True only if the real SAM2 backend can actually be constructed.

    Used by ``real_backend`` skip guards. This attempts construction rather than checking
    ``importlib.util.find_spec("sam2")``, because a module merely *named* like the backend may be
    discoverable on the path yet not provide the real predictor (a partial install, etc.).
    Construction performs the same deferred ``torch``/``sam2`` import the backend uses and raises
    ``ImportError`` when the dependency is genuinely unusable, so the guard skips rather than
    hard-failing in that case.
    """
    from organ_masker_lite.sam2 import Sam2Backend

    try:
        Sam2Backend()
    except ImportError:
        return False
    return True
