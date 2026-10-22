"""Read an OME-Zarr v0.5 multiscale image: levels, axes, and lazy arrays."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zarr
from ome_zarr_models.v05.image import Image

from ..config import COARSEST_LEVEL


class ReaderError(ValueError):
    """Raised when the input cannot be read as an OME-Zarr v0.5 multiscale image."""


@dataclass
class LevelInfo:
    index: int
    path: str
    shape: tuple[int, ...]


class OmeZarrReader:
    """Lazy reader over an OME-Zarr v0.5 multiscale image."""

    def __init__(self, store_path: str | Path):
        self.store_path = Path(store_path)
        try:
            group = zarr.open_group(str(self.store_path), mode="r")
            self._image = Image.from_zarr(group)
        except Exception as exc:  # noqa: BLE001 - surface a clear domain error
            raise ReaderError(
                f"cannot read OME-Zarr v0.5 image at {self.store_path}: {exc}"
            ) from exc
        ms = self._image.attributes.ome.multiscales[0]
        self.axes: list[str] = [a.name for a in ms.axes]
        self._datasets = list(ms.datasets)
        if not self._datasets:
            raise ReaderError("multiscale image exposes no levels")
        self.levels: list[LevelInfo] = []
        for i, ds in enumerate(self._datasets):
            arr = self._open_array(ds.path)
            self.levels.append(LevelInfo(index=i, path=ds.path, shape=tuple(arr.shape)))

    def _open_array(self, path: str) -> zarr.Array:
        return zarr.open_array(store=str(self.store_path), path=path, mode="r")

    @property
    def n_levels(self) -> int:
        return len(self.levels)

    def default_level(self) -> int:
        """The coarsest level (highest index) is the default (research R5)."""
        return self.n_levels - 1

    def describe_levels(self) -> str:
        """Human-readable list of available levels and their shapes (for error reporting)."""
        return ", ".join(f"{lvl.index} {tuple(lvl.shape)}" for lvl in self.levels)

    def resolve_level(self, level: int) -> int:
        """Resolve a requested level, mapping the COARSEST sentinel; validate bounds (FR-003)."""
        if level == COARSEST_LEVEL:
            return self.default_level()
        if not (0 <= level < self.n_levels):
            raise ReaderError(
                f"level {level} does not exist; available levels: {self.describe_levels()}"
            )
        return level

    def level_shape(self, level: int) -> tuple[int, ...]:
        return self.levels[level].shape

    def level_storage(self, level: int) -> tuple[tuple[int, ...], tuple[int, ...] | None]:
        """The level array's ``(chunks, shards)``; ``shards`` is ``None`` when it isn't sharded."""
        arr = self._open_array(self._datasets[level].path)
        return tuple(arr.chunks), (tuple(arr.shards) if arr.shards is not None else None)

    def level_transform(self, level: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """The level's ``(scale, translation)`` per axis; 1 and 0 where the metadata omits them."""
        ndim = len(self.axes)
        scale = (1.0,) * ndim
        translation = (0.0,) * ndim
        for t in self._datasets[level].coordinateTransformations:
            if getattr(t, "scale", None) is not None:
                scale = tuple(float(v) for v in t.scale)
            if getattr(t, "translation", None) is not None:
                translation = tuple(float(v) for v in t.translation)
        return scale, translation

    def read_level(self, level: int) -> np.ndarray:
        """Read a level fully into memory (callers choose a level small enough to fit)."""
        return np.asarray(self._open_array(self._datasets[level].path)[:])

    def multiscale_model(self) -> Image:
        return self._image
