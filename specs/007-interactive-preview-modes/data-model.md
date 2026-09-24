# Phase 1 Data Model: Tiered Interactive Preview Modes

No new domain entity or on-disk schema change. One new config field, plus in-memory UI state.

## `RunConfig` (`src/organ_masker_lite/config.py`)

New field:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `frame_range` | `tuple[int, int] \| None` | `None` | Inclusive `(start, end)` frame bounds on the prompted/swept axis; `None` means the full axis (today's behavior, unchanged for the CLI/API) |

Validation: if set, `0 <= start <= end < n_frames` for the resolved level's swept axis (checked in
`compute_mask`, mirroring how `prompts.validate` already bounds-checks frame indices against
`level_shape`).

## `compute_mask` (`engine/pipeline.py`)

Behavior change, additive: when `config.frame_range` is set, `compute_mask` crops the prompted-axis
volume to that range, remaps prompt frame indices into the crop's local coordinates before calling
the existing, unmodified `run_sweep`, and places the cropped result back into a full-volume-shaped
boolean array at the correct offset before continuing (post-processing, record-building) exactly
as today. Callers (`interactive.py`) always receive a volume-shaped array back, whether or not
`frame_range` was set. `run_sweep` itself needs no change (`engine/sweep.py` untouched).

## Interactive session preview mode (`interactive.py`, in-memory only)

| Concept | Representation | Notes |
|---|---|---|
| Preview mode | One of `single-slice`, `few-slices`, `whole-volume` | Determines the `frame_range` passed to `preview()`/`compute_mask`: `(current, current)` for single-slice, `(current - 5, current + 5)` clipped to `[0, n_frames)` for few-slices (fixed half-width of 5 frames, 11 total), `None` for whole-volume |
| Busy guard | `_PreviewBusyGuard` — a small pure class with `try_start() -> bool` / `finish() -> None` | Display-independent, unit-testable without napari/Qt (fast tests, unlike `launch()`'s GUI wiring); `try_start()` returns `False` (no-op) if already busy, guarding FR-011 for both single-slice and few-slices |
| Busy indicator | napari `viewer.status` text (or equivalent lightweight UI signal) | Shown for the duration of an async single-slice/few-slices computation, driven by `_PreviewBusyGuard`'s state; not a determinate progress bar, since these operations have no meaningful sub-step percentage |
| Window clip | `_clip_window(current: int, half_width: int, n_frames: int) -> tuple[int, int]` | Pure, unit-testable helper computing the few-slices `frame_range`; `half_width=5` (data-model.md above). Used only by few-slices, not single-slice/whole-volume. |

## Shared "preview" layer merge semantics

- Whole-volume mode: replaces the entire layer's data (matches today's behavior — every frame was
  recomputed).
- Single-slice/few-slices mode: only the frame indices covered by that mode's `frame_range` are
  written into the existing layer's data array; every other frame's existing value is preserved
  unchanged (research R3). If the layer doesn't exist yet, it's created zero-filled at the full
  volume shape first, then the computed range is written in.
