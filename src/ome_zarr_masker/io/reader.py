"""Read an OME-Zarr v0.5 multiscale image: levels, axes, and lazy arrays."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zarr
from ome_zarr_models.v05.image import Image

from ..config import COARSEST_LEVEL
from .location import RemoteStoreError, StoreLocation, remote_errors


class ReaderError(ValueError):
    """Raised when the input cannot be read as an OME-Zarr v0.5 multiscale image."""


@dataclass
class LevelInfo:
    index: int
    path: str
    shape: tuple[int, ...]


class OmeZarrReader:
    """Lazy reader over an OME-Zarr v0.5 multiscale image, local or remote (feature 010).

    ``location`` is where the store lives; ``store_path`` is its local path (``None`` for a
    remote store). Remote stores are read through zarr, so only the metadata and the levels
    actually read are fetched (FR-008); provider failures raise ``RemoteStoreError``.
    """

    def __init__(self, store_path: str | Path | StoreLocation):
        self.location = StoreLocation.parse(store_path)
        self.store_path: Path | None = self.location.path
        try:
            with remote_errors(self.location):
                self._store = self.location.open_store(read_only=True)
                group = zarr.open_group(self._store, mode="r")
                self._image = Image.from_zarr(group)
        except Exception as exc:  # noqa: BLE001 - surface a clear domain error
            if isinstance(exc, RemoteStoreError):
                raise
            raise ReaderError(
                f"cannot read OME-Zarr v0.5 image at {self.location.display}: {exc}"
            ) from exc
        ms = self._image.attributes.ome.multiscales[0]
        self.axes: list[str] = [a.name for a in ms.axes]
        self._datasets = list(ms.datasets)
        if not self._datasets:
            raise ReaderError("multiscale image exposes no levels")
        self.levels: list[LevelInfo] = []
        self._arrays: dict[str, zarr.Array] = {}  # opened once: no repeated metadata fetches
        for i, ds in enumerate(self._datasets):
            arr = self._open_array(ds.path)
            self.levels.append(LevelInfo(index=i, path=ds.path, shape=tuple(arr.shape)))

    def _open_array(self, path: str) -> zarr.Array:
        if path not in self._arrays:
            with remote_errors(self.location):
                self._arrays[path] = zarr.open_array(store=self._store, path=path, mode="r")
        return self._arrays[path]

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
        arr = self._open_array(self._datasets[level].path)
        with remote_errors(self.location):
            return np.asarray(arr[:])

    def multiscale_model(self) -> Image:
        return self._image
