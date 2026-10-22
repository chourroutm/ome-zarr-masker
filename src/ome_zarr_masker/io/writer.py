"""Write a binary mask as an OME-Zarr v0.5 image matching the input's levels."""

from __future__ import annotations

import itertools
import json
import math
import os
import shutil
import warnings
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zarr
from ome_zarr_models.v05.axes import Axis
from ome_zarr_models.v05.image import Image
from pydantic_zarr.v3 import ArraySpec
from zarr.codecs import BloscCodec

from ..geometry import nearest_index
from .reader import OmeZarrReader

#: Default inner chunk shape for output levels whose input level isn't sharded (research R1).
DEFAULT_CHUNKS = (64, 64, 64)
#: Default shard edge, capped to each level's (chunk-rounded) size.
DEFAULT_MAX_SHARD = 1024
#: Default memory budget for shards written at the same time, beyond the run-level mask (FR-002).
WRITE_BUDGET_BYTES = 8 * 2**30
#: Compressor for every output level: well suited to binary masks (research R1).
COMPRESSOR = BloscCodec(cname="zstd", clevel=3, shuffle="bitshuffle")


class WriterError(RuntimeError):
    """Raised when the output cannot be written."""


@dataclass(frozen=True)
class LevelLayout:
    """How one output level is stored: inner chunks grouped into shards (data-model.md)."""

    level: int
    shape: tuple[int, ...]
    chunks: tuple[int, ...]
    shards: tuple[int, ...]
    source: str  # "input" when copied from a sharded input level, else "default"


def _default_layout(shape: tuple[int, ...], level: int = 0) -> LevelLayout:
    """64³ chunks in shards of up to ``DEFAULT_MAX_SHARD`` per axis, each a chunk multiple."""
    chunks = tuple(DEFAULT_CHUNKS)
    shards = tuple(
        min(DEFAULT_MAX_SHARD, -(-dim // c) * c) for dim, c in zip(shape, chunks, strict=True)
    )
    return LevelLayout(level, tuple(shape), chunks, shards, "default")


def _shard_regions(layout: LevelLayout) -> Iterator[tuple[slice, ...]]:
    """Shard-aligned regions tiling the level once (the last region per axis may be ragged)."""
    starts = (range(0, dim, s) for dim, s in zip(layout.shape, layout.shards, strict=True))
    for origin in itertools.product(*starts):
        yield tuple(
            slice(o, min(o + s, dim))
            for o, s, dim in zip(origin, layout.shards, layout.shape, strict=True)
        )


def _nn_indices(src_shape, src_scale, src_trans, dst_shape, dst_scale, dst_trans) -> list:
    """Per-axis source index for every target voxel: physical nearest neighbour (FR-006).

    Each target voxel centre is placed in the run level through both levels' scale and translation
    and takes the nearest run-level centre, exact ties to the lower index, clipped to the level.
    """
    return [
        np.clip(nearest_index(np.arange(t), ds, dt, ss, st), 0, s - 1)
        for s, ss, st, t, ds, dt in zip(
            src_shape, src_scale, src_trans, dst_shape, dst_scale, dst_trans, strict=True
        )
    ]


def _array_spec(layout: LevelLayout, axes: list[str]) -> ArraySpec:
    """Sharded, blosc-compressed uint8 spec with ``fill_value=0`` for one output level (R5)."""
    template = zarr.create_array(
        store=zarr.storage.MemoryStore(),
        shape=layout.shape,
        dtype="uint8",
        chunks=layout.chunks,
        shards=layout.shards,
        fill_value=0,
        compressors=COMPRESSOR,
        dimension_names=list(axes),
    )
    return ArraySpec.from_zarr(template)


def plan_layouts(reader: OmeZarrReader) -> list[LevelLayout]:
    """The storage layout of every output level (FR-007).

    A sharded input level's chunks and shards are copied, so the mask lines up with the image it
    belongs to; any other level gets the default sharded layout (the output is always sharded).
    """
    layouts = []
    for i in range(reader.n_levels):
        shape = reader.level_shape(i)
        chunks, shards = reader.level_storage(i)
        if shards is None:
            layouts.append(_default_layout(shape, i))
        else:
            layouts.append(LevelLayout(i, tuple(shape), chunks, shards, "input"))
    return layouts


def _check_workers(workers: object) -> int:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise WriterError(f"workers must be an integer >= 1, got {workers!r}")
    return workers


def resolve_workers(workers: int | None, layout: LevelLayout) -> int:
    """How many shards of ``layout`` to write at once (FR-002, FR-011, research R3).

    A user-set count is used as is. Otherwise as many as fit in ``WRITE_BUDGET_BYTES`` at about
    two shards' worth of memory each (the block plus encode buffers), never more than the CPU
    count and never fewer than one -- with a warning when even one doesn't fit.
    """
    if workers is not None:
        return _check_workers(workers)
    per_worker = 2 * math.prod(layout.shards)
    if per_worker > WRITE_BUDGET_BYTES:
        warnings.warn(
            f"one shard of level {layout.level} {layout.shards} needs about {per_worker} bytes, "
            f"more than the {WRITE_BUDGET_BYTES}-byte write budget; writing one shard at a time",
            UserWarning,
            stacklevel=2,
        )
        return 1
    return max(1, min(os.cpu_count() or 1, WRITE_BUDGET_BYTES // per_worker))


def _level_transforms(reader: OmeZarrReader) -> tuple[list[list[float]], list[list[float] | None]]:
    """Per-level scale and translation, as written into the output metadata (``None`` if absent)."""
    ms = reader.multiscale_model().attributes.ome.multiscales[0]
    scales: list[list[float]] = []
    translations: list[list[float] | None] = []
    for ds in ms.datasets:
        scale: list[float] | None = None
        translation: list[float] | None = None
        for t in ds.coordinateTransformations:
            if getattr(t, "scale", None) is not None:
                scale = list(t.scale)
            if getattr(t, "translation", None) is not None:
                translation = list(t.translation)
        scales.append(scale if scale is not None else [1.0] * len(reader.axes))
        translations.append(translation)
    return scales, translations


def _layout_record(layout: LevelLayout) -> dict:
    """One level's entry in the run record's ``output_layout`` (FR-012; no worker count)."""
    return {
        "level": layout.level,
        "shape": list(layout.shape),
        "chunks": list(layout.chunks),
        "shards": list(layout.shards),
        "compressor": {"name": "blosc", "cname": "zstd", "clevel": 3, "shuffle": "bitshuffle"},
        "source": layout.source,
    }


def _build_block(mask: np.ndarray, idx: list[np.ndarray], region: tuple[slice, ...]) -> np.ndarray:
    """The output block for one shard region, read straight from the run-level mask.

    Indexes one axis at a time (``np.take``) rather than with an ``np.ix_`` outer index, which is
    several times slower on shard-sized blocks; an axis whose indices are consecutive becomes a
    plain slice. Index vectors are non-decreasing, so a span equal to the length means consecutive.
    """
    block = mask
    for axis, (i, r) in enumerate(zip(idx, region, strict=True)):
        v = i[r]
        if int(v[-1]) - int(v[0]) + 1 == v.size:
            sl = [slice(None)] * block.ndim
            sl[axis] = slice(int(v[0]), int(v[-1]) + 1)
            block = block[tuple(sl)]
        else:
            block = np.take(block, v, axis=axis)
    return block


def _write_shard(z: zarr.Array, mask: np.ndarray, idx: list[np.ndarray], region) -> None:
    """Write one shard, skipping it entirely when its source region has no foreground (FR-005)."""
    source = tuple(
        slice(int(i[r].min()), int(i[r].max()) + 1) for i, r in zip(idx, region, strict=True)
    )
    if not mask[source].any():
        return
    z[region] = _build_block(mask, idx, region)


def _write_level(z, mask, idx, regions, workers, level, report) -> None:
    """Write every shard region of one level with at most ``workers`` running at once."""
    n = len(regions)
    done = last_decile = 0
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [pool.submit(_write_shard, z, mask, idx, r) for r in regions]
        for future in as_completed(futures):
            future.result()  # re-raises the first worker failure; ``finally`` cancels the rest
            done += 1
            decile = done * 10 // n
            if decile > last_decile:
                last_decile = decile
                report(f"level {level}: {done}/{n} shards written")
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def write_mask(
    output_path: str | Path,
    mask: np.ndarray,
    run_level: int,
    reader: OmeZarrReader,
    run_record: dict,
    overwrite: bool = False,
    *,
    workers: int | None = None,
    progress: Callable[[str], None] | None = None,
    on_level: Callable[[LevelLayout, int, int, str], None] | None = None,
) -> Path:
    """Write ``mask`` (binary, at ``run_level`` shape) as OME-Zarr v0.5 (FR-002, FR-013, FR-014).

    The output has the same levels, shapes, axes and transforms as the input. Each level is a
    sharded, blosc-compressed array written one shard at a time (feature 009): every shard's block
    comes straight from the run-level mask by physical nearest neighbour, so no level is ever held
    in memory whole. ``workers`` overrides the budget-derived number of shards written at once;
    ``progress`` receives per-level messages; ``on_level(layout, n_shards, workers, source)`` is
    called as each level starts. Nothing replaces an existing output until the write succeeds.
    """
    if workers is not None:
        _check_workers(workers)
    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        raise WriterError(f"output already exists: {output_path} (use overwrite to replace it)")

    def report(msg: str) -> None:
        if progress is not None:
            progress(msg)

    mask = (np.asarray(mask) != 0).astype(np.uint8)
    axis_names = list(reader.axes)
    layouts = plan_layouts(reader)
    scales, translations = _level_transforms(reader)
    run_scale, run_trans = reader.level_transform(run_level)

    tmp_path = output_path.with_name(output_path.name + ".tmp")
    if tmp_path.exists():
        shutil.rmtree(tmp_path)
    try:
        image = Image.new(
            array_specs=[_array_spec(lay, axis_names) for lay in layouts],
            paths=[str(lay.level) for lay in layouts],
            axes=[Axis(name=name, type="space") for name in axis_names],
            scales=scales,
            translations=translations,
        )
        image.to_zarr(zarr.storage.LocalStore(str(tmp_path)), path="")
        for lay in layouts:
            scale, trans = reader.level_transform(lay.level)
            idx = _nn_indices(mask.shape, run_scale, run_trans, lay.shape, scale, trans)
            n_workers = resolve_workers(workers, lay)
            source = "user" if workers is not None else "budget"
            regions = list(_shard_regions(lay))
            if workers is None:
                n_workers = min(n_workers, len(regions))  # report what can actually run
            if on_level is not None:
                on_level(lay, len(regions), n_workers, source)
            report(
                f"writing level {lay.level} {lay.shape}: {len(regions)} shards "
                f"({lay.chunks} chunks in {lay.shards} shards, workers={n_workers} ({source}))"
            )
            z = zarr.open_array(store=str(tmp_path), path=str(lay.level), mode="r+")
            _write_level(z, mask, idx, regions, n_workers, lay.level, report)
        record = {**run_record, "output_layout": [_layout_record(lay) for lay in layouts]}
        (tmp_path / "run_record.json").write_text(json.dumps(record, indent=2))

        if output_path.exists():
            shutil.rmtree(output_path)
        tmp_path.rename(output_path)
    except Exception:
        if tmp_path.exists():
            shutil.rmtree(tmp_path, ignore_errors=True)
        raise
    return output_path
