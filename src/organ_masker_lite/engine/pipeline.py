"""Masking pipeline: preflight -> validate -> sweep -> combine -> write."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import RunConfig
from ..io.reader import OmeZarrReader, ReaderError
from ..io.validate import validate_ome_zarr
from ..io.writer import write_mask
from ..postprocess.morphology import postprocess_mask
from ..prompts.model import Prompt, PromptError, PromptSet
from ..sam2 import Sam2Backend
from .combine import VoteAccumulator
from .sweep import run_sweep, seeds_from_mask


class PipelineError(RuntimeError):
    """Raised when a masking run cannot proceed."""


def estimate_intermediate_bytes(level_shape: tuple[int, ...]) -> int:
    """Estimate intermediate on-disk bytes: RGB frame stack + uint16 vote accumulator."""
    voxels = int(np.prod(level_shape))
    return voxels * 3 + voxels * 2


def _axis_dir(workdir: str | Path, axis_name: str) -> Path:
    """A per-axis working subdirectory so concurrent frame stacks do not collide."""
    path = Path(workdir) / f"axis_{axis_name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _crop_to_frame_range(
    volume: np.ndarray,
    prompts: PromptSet,
    frame_range: tuple[int, int],
    axis_index: int,
) -> tuple[np.ndarray, PromptSet, int]:
    """Crop ``volume`` along ``axis_index`` to the inclusive ``frame_range`` and remap ``prompts``.

    Prompts whose ``frame_index`` falls outside ``frame_range`` are dropped (feature 007, FR-004);
    the rest are remapped to local (cropped) frame indices. Returns ``(cropped_volume,
    remapped_prompts, offset)`` where ``offset == frame_range[0]``, for use by
    :func:`_place_at_offset`.
    """
    start, end = frame_range
    slicer: list[slice] = [slice(None)] * volume.ndim
    slicer[axis_index] = slice(start, end + 1)
    cropped = volume[tuple(slicer)]

    remapped = [
        Prompt(
            frame_index=p.frame_index - start,
            point_coords=p.point_coords.copy(),
            point_labels=p.point_labels.copy(),
            box=None if p.box is None else p.box.copy(),
            obj_id=p.obj_id,
        )
        for p in prompts.prompts
        if start <= p.frame_index <= end
    ]
    return cropped, PromptSet(remapped), start


def _place_at_offset(
    cropped: np.ndarray, offset: int, axis_index: int, full_shape: tuple[int, ...]
) -> np.ndarray:
    """Place a cropped boolean mask into a zero-filled array of ``full_shape`` at ``offset``.

    Every frame outside ``[offset, offset + cropped.shape[axis_index])`` along ``axis_index``
    stays background (``False``) -- nothing was computed there (feature 007, research R3).
    """
    full = np.zeros(full_shape, dtype=bool)
    slicer: list[slice] = [slice(None)] * len(full_shape)
    slicer[axis_index] = slice(offset, offset + cropped.shape[axis_index])
    full[tuple(slicer)] = cropped
    return full


def preflight_disk(required_bytes: int, path: str | Path) -> None:
    """Fail clearly if the working directory lacks room for intermediates (FR-016)."""
    free = shutil.disk_usage(str(path)).free
    if required_bytes > free:
        raise PipelineError(
            f"insufficient disk for intermediates: need ~{required_bytes} bytes, "
            f"{free} available at {path}"
        )


@dataclass
class MaskComputation:
    """The result of computing a consensus mask, plus everything needed to write it (FR-014)."""

    consensus: np.ndarray
    level: int
    reader: OmeZarrReader
    record: dict


def compute_mask(
    input_path: str | Path,
    prompts: PromptSet,
    config: RunConfig,
    *,
    reader: OmeZarrReader | None = None,
    backend: Sam2Backend | None = None,
    progress: Callable[[str], None] | None = None,
    run_id: str | None = None,
) -> MaskComputation:
    """Validate, sweep, and combine into a consensus mask (no output written).

    Shared by the CLI (``run_masking``) and the programmatic API so both produce identical masks
    and run records for identical inputs/prompts (SC-005). ``reader`` may be injected (tests).
    Segmentation always uses SAM2; ``backend`` may optionally be an already-constructed
    :class:`Sam2Backend` so callers making several runs (e.g. benchmarks) reuse one loaded
    predictor instead of paying checkpoint-load cost on every call. This is a reuse seam, not a
    selector -- there is no other backend to pass.
    """

    def report(msg: str) -> None:
        if progress is not None:
            progress(msg)

    report("validating input")
    validate_ome_zarr(input_path)

    reader = reader or OmeZarrReader(input_path)
    level = reader.resolve_level(config.level)

    if not config.axes:
        raise PipelineError("at least one sweep axis is required")
    for axis_name in config.axes:
        if axis_name not in reader.axes:
            raise PipelineError(f"axis '{axis_name}' not in input axes {reader.axes}")
    prompted_axis = config.axes[0]
    prompted_index = reader.axes.index(prompted_axis)
    level_shape = reader.level_shape(level)

    # Convert prompts authored at a different level to this run's level (feature
    # 008-level-agnostic-prompts, FR-004/FR-008) before validating against it.
    if prompts.level is not None and prompts.level != level:
        if not (0 <= prompts.level < reader.n_levels):
            raise PromptError(
                f"prompt set was authored at level {prompts.level}, which does not exist for "
                f"this input; available levels: {reader.describe_levels()}"
            )
        prompts = prompts.resolved_between(
            reader.level_transform(prompts.level), reader.level_transform(level), prompted_index
        )

    # The user places landmarks on the prompted axis's planes; validate against that axis (FR-022).
    prompts.validate(level_shape, prompted_index)

    report(f"reading level {level} {level_shape}")
    volume = reader.read_level(level)

    frame_offset = 0
    working_shape = level_shape
    if config.frame_range is not None:
        start, end = config.frame_range
        n_frames = level_shape[prompted_index]
        if not (0 <= start <= end < n_frames):
            raise PipelineError(
                f"frame_range {config.frame_range} out of bounds for {n_frames} frames "
                f"on axis '{prompted_axis}'"
            )
        volume, prompts, frame_offset = _crop_to_frame_range(
            volume, prompts, config.frame_range, prompted_index
        )
        working_shape = volume.shape

    if backend is None:
        try:
            backend = Sam2Backend(config=config)
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="organ_masker_") as workdir:
        preflight_disk(estimate_intermediate_bytes(working_shape), workdir)
        accumulator = VoteAccumulator(working_shape, workdir)

        # Sweep the prompted axis first; its 3D mask seeds the other selected axes (FR-022).
        report(f"sweeping prompted axis '{prompted_axis}' ({config.direction})")
        seed_mask = run_sweep(
            volume,
            prompted_index,
            prompts,
            backend,
            _axis_dir(workdir, prompted_axis),
            config.direction,
        )
        if not seed_mask.any():
            raise PipelineError(
                "the prompted-axis sweep produced no foreground; cannot seed the other axes "
                "(check the prompts and the selected level)"
            )
        accumulator.add(seed_mask)

        for axis_name in config.axes[1:]:
            axis_index = reader.axes.index(axis_name)
            axis_prompts = seeds_from_mask(seed_mask, axis_index)
            if not axis_prompts.prompts:
                report(f"skipping axis '{axis_name}': no seeds derived")
                continue
            report(f"sweeping seeded axis '{axis_name}' ({config.direction})")
            mask = run_sweep(
                volume,
                axis_index,
                axis_prompts,
                backend,
                _axis_dir(workdir, axis_name),
                config.direction,
            )
            accumulator.add(mask)

        consensus = accumulator.result(config.combine_rule)

    if not config.postprocess.is_noop:
        report("post-processing mask")
        consensus = postprocess_mask(consensus, config.postprocess)

    if config.frame_range is not None:
        consensus = _place_at_offset(consensus, frame_offset, prompted_index, level_shape)

    record = {
        "run_id": run_id,
        "input": str(input_path),
        "level": level,
        "config": config.to_record(),
        "prompts": prompts.to_record(),
    }
    return MaskComputation(consensus=consensus, level=level, reader=reader, record=record)


def run_masking(
    input_path: str | Path,
    output_path: str | Path,
    prompts: PromptSet,
    config: RunConfig,
    *,
    reader: OmeZarrReader | None = None,
    backend: Sam2Backend | None = None,
    progress: Callable[[str], None] | None = None,
    run_id: str | None = None,
    workers: int | None = None,
    on_level=None,
) -> Path:
    """Run an end-to-end masking pipeline and write an OME-Zarr v0.5 mask.

    ``reader``/``backend`` may be injected; otherwise they are constructed from ``input_path``/
    ``config``. Segmentation always uses SAM2. ``run_id`` is embedded in the run record for log
    correlation. ``workers``/``on_level`` are passed to the writer (feature 009): shards written in
    parallel, and a per-level callback (used by the CLI's input log).
    """
    comp = compute_mask(
        input_path,
        prompts,
        config,
        reader=reader,
        backend=backend,
        progress=progress,
        run_id=run_id,
    )
    if progress is not None:
        progress("writing output")
    write_mask(
        output_path,
        comp.consensus,
        comp.level,
        comp.reader,
        comp.record,
        overwrite=config.overwrite,
        workers=workers,
        progress=progress,
        on_level=on_level,
    )
    return Path(output_path)


__all__ = [
    "run_masking",
    "compute_mask",
    "MaskComputation",
    "PipelineError",
    "estimate_intermediate_bytes",
    "preflight_disk",
    "ReaderError",
]
