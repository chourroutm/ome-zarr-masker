# Implementation Plan: Tiered Interactive Preview Modes

**Branch**: `007-interactive-preview-modes` | **Date**: 2026-09-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-interactive-preview-modes/spec.md`

## Summary

Replace the interactive session's single, always-whole-volume `p` preview with three modes and
three shortcuts: single-slice and few-slices (a fixed-window, current-slice-centered range) run
asynchronously on a background thread with a busy indicator so the UI never freezes; whole-volume
reproduces today's exact behavior but is gated behind an explicit confirmation dialog. All three
write into the one existing shared "preview" layer, merging into just the frames they recomputed
rather than replacing the whole array. Requires a small, additive change to the shared masking
engine (`config.py`/`engine/pipeline.py`) to support a bounded frame range, plus
the async/dialog/merge logic in `interactive.py`.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged)

**Primary Dependencies**: `napari` (existing `[interactive]` extra) for
`napari.qt.threading.thread_worker` (background execution) and `qtpy.QtWidgets.QMessageBox`
(confirmation dialog) — both already transitively available through napari's own dependency chain,
so no new package is added. No other new dependency.

**Storage**: Unchanged — OME-Zarr v0.5. This feature only changes how/when the interactive
session's in-memory preview is computed and displayed; nothing about the written export format
changes.

**Testing**: `pytest`. The frame-range engine change (`compute_mask` bounded to a range) is
testable headlessly and fast, same pattern as existing engine tests, plus a real_backend-gated
performance benchmark for SC-001/SC-002 (Constitution Principle IV). Two pieces of `interactive.py`
logic that don't actually need a display — the busy-guard state machine (FR-011) and the few-slices
window-clip arithmetic (FR-004) — are pulled out into pure, unit-tested helpers rather than left
inside the untestable GUI boundary. What remains genuinely display-dependent (layer creation,
keybinding wiring, the confirmation dialog, `viewer.status` updates) lives in `launch()`, which —
per this project's existing, unchanged testing boundary (see feature 006's plan) — has no automated
coverage (no display in this environment's test runs); it's validated via `quickstart.md`'s manual
walkthrough, same as feature 006.

**Target Platform**: Unchanged — Linux/macOS workstation with a display for the interactive
session; optional GPU.

**Project Type**: Single Python package; napari view stays a thin layer over the headless core.

**Performance Goals** (Principle IV): New, explicit targets, directly from the spec, validated by a
dedicated benchmark (`tests/performance/test_frame_range_perf.py`, real_backend-gated, mirroring
`tests/performance/test_benchmark.py`'s existing pattern): single-slice preview (`frame_range=(f,
f)`, a single SAM2 image-level call, not a video-propagation sweep) on a real, large volume MUST
complete in under 10 seconds (SC-001). Few-slices preview (fixed ±5-frame window, 11 frames total)
MUST show comparable timing across volumes of very different total depth — i.e. cost scales with
the fixed window, not volume depth (SC-002). Whole-volume preview/export keep the existing spec-001
budget (512³ in <5 minutes on GPU) — this feature does not change that computation, only when it's
allowed to run.

**Constraints**: No new dependency (research confirms `thread_worker`/`QMessageBox` are already
available). Single-slice/few-slices computation MUST NOT block the GUI thread (FR-010). A preview
trigger while one is already in flight MUST be a no-op, not queued or cancelling (FR-011).

**Scale/Scope**: Touches `config.py` (new `RunConfig.frame_range` field) and `engine/pipeline.py`
(crop the volume + remap prompt frame indices before calling `run_sweep`, then place its result
back at the correct offset). `engine/sweep.py` needs no change at all — `run_sweep` already takes
an arbitrary volume/prompts and has no notion of "the full axis," so handing it a pre-cropped
volume with remapped prompts works unmodified (discovered while tracing the exact call shape;
corrects the Phase 0 assumption that `sweep.py` would need touching). Plus `interactive.py` (three
shortcuts, threading, confirmation dialog, merge-into-shared-layer logic). `cli.py`/`api.py`'s
public surface is unaffected — `frame_range` defaults to `None` (full range, today's behavior)
everywhere except the interactive session's fast-tier calls.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.0 (four core principles):

- **I. Code Quality Standards** — PASS. Reuses napari's own public threading/dialog primitives
  rather than hand-rolling thread management; the frame-range engine change is additive
  (`None` = today's behavior everywhere except the new fast-tier call sites) rather than a
  behavior-changing rewrite.
- **II. Test Discipline (NON-NEGOTIABLE)** — PASS, with the same disclosed, pre-existing limitation
  as feature 006: `launch()`'s GUI wiring has no automated coverage (no display in this
  environment). The frame-range engine change (the one piece with real logic and no display
  dependency) gets full fast, deterministic test coverage; the GUI-only parts (threading, dialog,
  merge-display) are covered by `quickstart.md`'s manual walkthrough, matching the existing
  boundary exactly — not widening it.
- **III. Disciplined Version Control** — PASS (planned). Atomic commits: (1) `RunConfig.frame_range`
  + `run_sweep`/`compute_mask` bounded-range support, (2) single-slice/few-slices shortcuts +
  background threading + busy indicator, (3) whole-volume confirmation dialog, (4) merge-not-
  replace logic for the shared preview layer, (5) tests — each leaving the suite green.
- **IV. Performance Requirements** — PASS. New, explicit targets stated above (SC-001/SC-002),
  directly from the spec's measurable outcomes; whole-volume's existing budget is unchanged.

No unjustified violations. No Complexity Tracking entries needed.

**Post-Phase-1 re-check**: Phase 1 design confirmed both new dependencies-in-spirit
(`thread_worker`, `QMessageBox`) are already transitively available via napari with zero new
packages, and the engine change (`RunConfig.frame_range`) is purely additive (`None` preserves
every existing caller's behavior byte-for-byte). No change to the Constitution Check outcome.

## Project Structure

### Documentation (this feature)

```text
specs/007-interactive-preview-modes/
├── plan.md              # This file
├── research.md          # Phase 0 output (threading, dialog, merge-semantics decisions)
├── data-model.md         # Phase 1 output (RunConfig.frame_range, preview-mode state)
├── quickstart.md        # Phase 1 output
├── contracts/            # Phase 1 output
│   └── interactive-preview.md
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
src/organ_masker_lite/
├── config.py                  # changed: RunConfig gains `frame_range: tuple[int, int] | None =
│                               #          None` (inclusive frame bounds on the prompted/swept axis)
├── engine/
│   └── pipeline.py             # changed: compute_mask honors config.frame_range when set via two
│                                #          new pure helpers (crop+remap before run_sweep,
│                                #          place-back after) -- run_sweep itself is unchanged
│                                #          (research R3)
└── interactive.py              # changed (primary file): three preview shortcuts, background
                                 #   threading via napari.qt.threading.thread_worker for
                                 #   single-slice/few-slices, a pure `_PreviewBusyGuard` helper
                                 #   guarding FR-011, a pure `_clip_window` helper for few-slices'
                                 #   window (both unit-testable, unlike the rest of launch()), a
                                 #   qtpy.QtWidgets.QMessageBox confirmation for whole-volume, and
                                 #   merge-into-shared-preview-layer logic (research R3)

tests/
├── unit/
│   ├── test_pipeline_frame_range.py    # NEW: fast, GPU-free unit tests of the pure crop+remap
│   │                                    #      and place-back helpers (no SAM2/backend involved)
│   └── test_interactive_preview_state.py  # NEW: fast, GPU-free unit tests of `_PreviewBusyGuard`
│                                           #      and `_clip_window` -- display-independent logic
│                                           #      pulled out of launch()'s untestable GUI boundary
├── integration/
│   └── test_frame_range.py             # NEW, real_backend-gated: compute_mask(frame_range=...)
│                                        #     end-to-end correctness against an unbounded run
└── performance/
    └── test_frame_range_perf.py        # NEW, real_backend-gated: SC-001 (<10s single-slice) and
                                         #     SC-002 (few-slices cost independent of volume depth),
                                         #     mirrors test_benchmark.py's existing pattern
```

**Structure Decision**: The frame-range capability lives in the existing engine modules that already
own "how a sweep is computed" (`config.py`/`engine/pipeline.py`), exactly where
`--dilate`/`--erode`/`--combine` already live as `RunConfig` fields threaded through the same
functions. The threading/dialog/merge UI logic stays entirely inside `interactive.py`, which
already owns the napari view. No new module.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

No constitution violations; no entries required.
