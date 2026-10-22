"""Shared test fixtures: a synthetic OME-Zarr v0.5 volume."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr
from ome_zarr_models.v05.axes import Axis
from ome_zarr_models.v05.image import Image
from pydantic_zarr.v3 import ArraySpec


def _spec(a: np.ndarray, chunks, shards) -> ArraySpec:
    if chunks is None:
        return ArraySpec.from_array(a, dimension_names=["z", "y", "x"])
    c = tuple(min(ci, s) for ci, s in zip(chunks, a.shape, strict=True))
    kw = {}
    if shards is not None:
        # a shard must be a whole multiple of the chunk, and need not exceed the array
        kw["shards"] = tuple(
            -(-min(si, s) // ci) * ci for si, s, ci in zip(shards, a.shape, c, strict=True)
        )
    template = zarr.create_array(
        store=zarr.storage.MemoryStore(),
        shape=a.shape,
        dtype=a.dtype,
        chunks=c,
        dimension_names=["z", "y", "x"],
        **kw,
    )
    return ArraySpec.from_zarr(template)


def write_ome_zarr(
    path: Path,
    level0: np.ndarray,
    n_levels: int = 2,
    axis_factors: tuple[int, int, int] = (2, 2, 2),
    *,
    chunks: tuple[int, int, int] | None = None,
    shards: tuple[int, int, int] | None = None,
    scales: list[list[float]] | None = None,
    translations: list[list[float] | None] | None = None,
) -> Path:
    """Write a minimal valid OME-Zarr v0.5 multiscale image (axes z, y, x).

    ``axis_factors`` is the per-axis (z, y, x) downsample factor between consecutive levels;
    the default ``(2, 2, 2)`` reproduces every pre-existing caller's isotropic pyramid exactly.
    Passing different factors per axis builds an anisotropic pyramid (feature
    008-level-agnostic-prompts, FR-004). ``chunks``/``shards`` store every level with that
    layout (capped to the level); ``scales``/``translations`` override the per-level transforms
    (feature 009-scalable-mask-writer). Defaults reproduce the original fixture exactly.
    """
    fz, fy, fx = axis_factors
    arrays = [level0]
    for _ in range(1, n_levels):
        arrays.append(arrays[-1][::fz, ::fy, ::fx].copy())
    axes = [Axis(name=n, type="space") for n in ("z", "y", "x")]
    specs = [_spec(a, chunks, shards) for a in arrays]
    image = Image.new(
        array_specs=specs,
        paths=[str(i) for i in range(n_levels)],
        axes=axes,
        scales=scales or [[float(f) ** i for f in axis_factors] for i in range(n_levels)],
        translations=translations or [None] * n_levels,
    )
    image.to_zarr(zarr.storage.LocalStore(str(path)), path="")
    for i, arr in enumerate(arrays):
        zarr.open_array(store=str(path), path=str(i), mode="r+")[:] = arr
    return path


def assert_ome_zarr_models_valid(path: Path) -> None:
    """Validate ``path`` with ome-zarr-models itself, independently of this project's wrapper.

    Runs the package's own ``ome-zarr-models validate`` CLI (installed next to this interpreter)
    and also opens the store in-process as OME-Zarr 0.5 with ``ValidationWarning`` promoted to
    an error, requiring a v0.5 ``Image`` back.
    """
    import subprocess
    import sys
    import warnings

    from ome_zarr_models import open_ome_zarr
    from ome_zarr_models.exceptions import ValidationWarning

    cli = Path(sys.executable).parent / "ome-zarr-models"
    proc = subprocess.run(
        [str(cli), "validate", str(path)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0 and "Valid OME-Zarr" in proc.stdout, proc.stdout + proc.stderr

    with warnings.catch_warnings():
        warnings.simplefilter("error", category=ValidationWarning)
        model = open_ome_zarr(str(path), version="0.5")
    assert isinstance(model, Image), type(model)


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
