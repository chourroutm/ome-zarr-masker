# Phase 0 Research: Tiered Interactive Preview Modes

## R1: Background execution for single-slice/few-slices (FR-010)

**Decision**: `napari.qt.threading.thread_worker` (confirmed present and public in the installed
napari: `napari.qt.threading.{thread_worker, create_worker, FunctionWorker, GeneratorWorker,
WorkerBase}`). Decorate the single-slice/few-slices computation function with `@thread_worker`;
its `started`/`returned`/`errored` signals are delivered back on the GUI thread via Qt's
queued-connection mechanism, so the `returned`-connected callback can safely update
`viewer.layers["preview"].data` without any manual thread-safety code.

**Rationale**: This is napari's own documented mechanism for exactly this situation (a plugin
callback that shouldn't block the GUI), already available with no new dependency. Handles the
thread lifecycle, error propagation, and safe GUI-thread callback delivery — hand-rolling this with
raw `threading.Thread`/`Qt` signals would reimplement what `thread_worker` already provides.

**Alternatives considered**: raw `threading.Thread` + manual Qt signal wiring — rejected, more code
for the same result with a real risk of a cross-thread napari layer update bug (napari/Qt layer
mutations must happen on the GUI thread); `asyncio` — rejected, napari's event loop is Qt-based,
not asyncio-based, so this would need its own bridge for no benefit over `thread_worker`.

## R2: Confirmation dialog for whole-volume mode (FR-006)

**Decision**: `qtpy.QtWidgets.QMessageBox.question(...)` (Yes/No), confirmed available — `qtpy` is
already an installed transitive dependency of napari (used throughout napari's own `_qt` dialogs,
e.g. `napari/_qt/dialogs/confirm_close_dialog.py`). No new dependency.

**Rationale**: `qtpy` abstracts over whichever Qt binding napari itself resolved to (PyQt5/PySide2/
etc.), so this dialog works correctly regardless of the user's installed Qt backend — the same
guarantee napari's own dialogs rely on. A blocking, modal `QMessageBox` is also the correct
mechanism for the spec's "answered before any other session interaction proceeds" requirement
(Edge Cases) — it's modal by construction.

**Alternatives considered**: `napari.utils.notifications` toast-style notification — rejected, not
a blocking confirm/cancel primitive, wrong shape for a gate the user must explicitly answer before
proceeding.

## R3: Merging a mode's result into the shared preview layer, and the frame-range engine change

**Question**: FR-007 says all three modes write into the same shared "preview" layer. If a
single-slice or few-slices result only covers a handful of frames, should that overwrite the
*entire* layer's data (discarding whatever a prior, larger computation had shown for the other
frames), or only the recomputed frames' slices?

**Decision**: Merge, never wholesale-replace. Setting `viewer.layers["preview"].data` MUST update
only the frame indices the triggered mode actually recomputed; every other frame keeps whatever
value it held before (from an earlier computation, or background/zero if the layer didn't exist
yet). This requires the engine to be able to compute a mask for a *bounded frame range* and hand
back just that range (or the full array with only that range populated), rather than always
returning a full-volume result.

**Rationale**: The alternative (replacing the whole array) would make a fast single-slice preview
visually erase a previous, more complete whole-volume result elsewhere in the volume — actively
misleading, and the opposite of what a "quick check" interaction should do. Implementing this
requires `compute_mask`/`run_sweep` to accept a bounded frame range on the swept axis (new
`RunConfig.frame_range: tuple[int, int] | None`, inclusive bounds, `None` = today's full-range
behavior): `compute_mask` crops the volume to that range before calling `run_sweep`, remaps
prompt frame indices into the cropped range's local coordinates, and places `run_sweep`'s
cropped-range output back at the correct offset in a full-volume-shaped array before returning
(so callers — including `interactive.py`'s merge logic — always get volume-shaped output,
simplifying the merge to "assign this range of indices" without offset arithmetic on the caller
side). The interactive session only ever uses a single sweep axis (`preview()`'s existing default
of `axes=["z"]` and current single-slice/few-slices scope per spec.md), so this frame-range
capability does not need to interact with the multi-axis seeding path (`seeds_from_mask`) at all —
only the prompted-axis sweep.

**Alternatives considered**: have `run_sweep`/`compute_mask` return just the cropped sub-array and
push offset bookkeeping onto every caller — rejected, `interactive.py` would need to duplicate
volume-shape/offset math that's simpler to keep inside the engine, once, next to where the crop
itself happens; replace the whole preview layer every time — rejected per the rationale above; keep
a separate preview layer per mode instead of merging into one — rejected, spec.md FR-007 explicitly
requires a single shared layer.

## R4: Extracting testable logic out of `launch()`'s untestable GUI boundary

**Question** (caught by `/speckit-analyze`, finding M2): `launch()` has no automated test coverage
in this project (no display in this environment). Does that mean every piece of FR-010/FR-011/
FR-004 logic added by this feature is automatically untestable too?

**Decision**: No — only what's genuinely display-dependent is exempt. Two pieces of this feature's
logic don't touch napari/Qt at all and can be pulled into small, pure, module-level functions in
`interactive.py`: a `_PreviewBusyGuard` class (`try_start()`/`finish()`, tracking whether a
computation is in flight for FR-011) and `_clip_window(current, half_width, n_frames)` (the
few-slices boundary-clipping arithmetic for FR-004). Both get fast unit tests
(`tests/unit/test_interactive_preview_state.py`). `launch()` itself just calls them — the
genuinely-untestable-without-a-display part shrinks to layer creation, keybinding registration, the
confirmation dialog, and `viewer.status` updates.

**Rationale**: Matches the same pattern already used for `frame_range` (R1-R3): don't let "this
function lives inside `launch()`" become an excuse to skip testing logic that has nothing to do
with napari's display. Directly serves Constitution Principle II.

**Alternatives considered**: leave the busy-guard and window-clip as inline logic inside the
keybinding callbacks (as originally task-planned) — rejected once flagged, since it needlessly
widens the untested surface for no implementation benefit.

## R5: Performance validation for SC-001/SC-002 (Constitution Principle IV)

**Question** (caught by `/speckit-analyze`, finding C1): spec.md sets explicit performance targets
for single-slice and few-slices preview. What validates them?

**Decision**: A new `real_backend`-gated benchmark, `tests/performance/test_frame_range_perf.py`,
mirroring the existing `tests/performance/test_benchmark.py` pattern: (1) `compute_mask(...,
frame_range=(f, f))` on a real volume completes in under 10 seconds (SC-001's concrete threshold);
(2) `compute_mask(..., frame_range=(f - 5, f + 5))` shows comparable wall-clock time on two
synthetic volumes of very different total depth, same window size (SC-002 — cost scales with the
window, not the volume).

**Rationale**: Matches Constitution Principle IV's requirement that performance-sensitive paths be
validated with benchmarks, not assumed. Reuses the project's existing benchmark infrastructure
and `real_backend` gating rather than inventing a new testing pattern.

**Alternatives considered**: leave it to manual observation during `quickstart.md`'s walkthrough —
rejected, a declared measurable target with no automated check is exactly what Principle IV's gate
exists to prevent.
