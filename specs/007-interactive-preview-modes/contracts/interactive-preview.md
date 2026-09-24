# Interactive Session Preview Contract: Tiered Modes

Extends [interactive-ui.md](../../006-interactive-prompt-layers/contracts/interactive-ui.md) (the
prompt-layer contract from feature 006). Supersedes only the single `p`-triggers-whole-volume
behavior implied by that document's C-UI-13; all other clauses there are unchanged.

## Modes and shortcuts

- **C-PV-1**: The session MUST expose three preview shortcuts, distinct from each other and from
  `n`/`y`/`e`: single-slice, few-slices, whole-volume (FR-001/FR-002).
- **C-PV-2**: Single-slice MUST compute using only the currently-viewed frame (`viewer.dims.
  current_step` on the swept axis) and only that frame's synced prompts (FR-003).
- **C-PV-3**: Few-slices MUST compute using a fixed ±5-frame window (11 frames total) centered on
  the current frame, clipped to `[0, n_frames)` via the pure `_clip_window` helper (research R4),
  using only prompts within that window (FR-004).
- **C-PV-4**: Whole-volume MUST reproduce the pre-existing `p` behavior exactly: full-axis
  propagation using every synced prompt (FR-005).

## Responsiveness and concurrency

- **C-PV-5**: Single-slice/few-slices computation MUST run via `napari.qt.threading.thread_worker`
  (research R1), never blocking the GUI thread; a busy indicator MUST be visible for the duration
  (FR-010).
- **C-PV-6**: While a single-slice/few-slices computation is in flight, any preview shortcut
  (including a repeat of the in-flight one) MUST be a no-op, enforced by the pure
  `_PreviewBusyGuard` helper (research R4) (FR-011).
- **C-PV-7**: Whole-volume mode MAY block the GUI thread synchronously; it does not need the
  `thread_worker` treatment, since it is already gated by C-PV-8's confirmation.

## Confirmation

- **C-PV-8**: Triggering whole-volume mode MUST first show a modal confirmation
  (`qtpy.QtWidgets.QMessageBox`, research R2) naming the cost/time implication; declining MUST run
  no computation and leave the current preview/session state unchanged (FR-006).
- **C-PV-9**: `e` (export) MUST NOT show this confirmation, and MUST always perform the full
  whole-volume computation regardless of the last-triggered preview mode (FR-008).

## Shared preview layer

- **C-PV-10**: All three modes MUST write into the one existing "preview" labels layer, never a
  per-mode layer (FR-007).
- **C-PV-11**: Single-slice/few-slices results MUST be merged into that layer at only the frame
  indices they recomputed; every other frame's existing content MUST be left unchanged (research
  R3). Whole-volume results replace the entire layer's data (every frame was recomputed).

## Engine (headless, non-UI)

- **C-PV-12**: `RunConfig.frame_range` (new, default `None`) MUST leave every existing caller's
  behavior byte-for-byte unchanged when unset; when set, `compute_mask` MUST crop, remap, compute,
  and place the result back at the correct offset in a full-volume-shaped array (data-model.md).

## Performance (Constitution Principle IV)

- **C-PV-13**: Single-slice preview (`frame_range=(f, f)`) MUST complete in under 10 seconds on a
  real, large volume (SC-001), verified by `tests/performance/test_frame_range_perf.py`.
- **C-PV-14**: Few-slices preview timing MUST NOT scale with total volume depth — verified by
  comparable wall-clock time for the same fixed window on volumes of very different depth (SC-002),
  same benchmark file.
