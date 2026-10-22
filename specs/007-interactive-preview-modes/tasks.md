---

description: "Task list for Tiered Interactive Preview Modes"
---

# Tasks: Tiered Interactive Preview Modes

**Input**: Design documents from `/specs/007-interactive-preview-modes/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/interactive-preview.md,
quickstart.md

**Tests**: REQUIRED for the engine layer and for any logic that doesn't require a display
(Principle II, NON-NEGOTIABLE) — the frame-range crop/remap/place-back logic, the export-safety
fix, the performance targets (Principle IV), and the pure `_PreviewBusyGuard`/`_clip_window`
helpers are all fully testable headlessly (research R1-R5). What remains genuinely
display-dependent — layer creation, keybinding wiring, the confirmation dialog, `viewer.status`
updates — carries the same pre-existing, unchanged `# pragma: no cover - requires napari + a
display` boundary as feature 006, validated by `quickstart.md`'s manual walkthrough instead.

**Organization**: Tasks are grouped by user story. A Foundational phase precedes them because US1
and US2 cannot exist without `RunConfig.frame_range`/the crop-remap-place-back engine support and
the shared `_PreviewBusyGuard` primitive; US3 (whole-volume) doesn't depend on `frame_range` but
shares `interactive.py` and the export-safety fix.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: User story label (US1/US2/US3) on user-story phase tasks only

## Path Conventions

Single Python package, `src/` layout: `src/ome_zarr_masker/`, tests in `tests/`.

---

## Phase 1: Foundational (blocking prerequisite for US1 and US2; also fixes a real export-safety
gap, and provides the busy-guard primitive shared by US1/US2)

**Purpose**: `RunConfig.frame_range` plus pure crop/remap/place-back helpers in `compute_mask`
(research R3); hardening `InteractiveSession.export()` so it can never silently export a cached
*partial* preview; a performance benchmark for the new SC-001/SC-002 targets (research R5,
Constitution Principle IV); and the pure, unit-testable `_PreviewBusyGuard` helper (research R4)
that both fast-tier modes will reuse for FR-011.

**⚠️ CRITICAL**: T009 (export-safety fix) must land no later than the first partial-preview mode
(US1) ships — do not defer it to US3's phase just because it's about whole-volume correctness.

### Tests (write first, must FAIL before T008-T011)

- [X] T001 [P] Unit test: a pure crop+remap helper — given a synthetic volume, a `PromptSet`, and a
      `frame_range`, returns the cropped volume slice and prompts remapped to local (cropped)
      frame indices plus the offset — in new file `tests/unit/test_pipeline_frame_range.py`
      (research R3, data-model.md)
- [X] T002 [P] Unit test: a pure place-back helper — given a small cropped boolean mask, an offset,
      and a full volume shape, returns a full-shape array with only that range populated and every
      other frame zero — same new file (research R3)
- [X] T003 [P] Unit test: `RunConfig().frame_range is None` by default; `RunConfig(frame_range=(a,
      b))` with `a > b` or negative bounds raises `ValueError` (mirrors the existing
      `dilation_radius`/`erosion_radius` validation style in `__post_init__`) — in
      `tests/unit/test_config.py` (data-model.md)
- [X] T004 [P] Integration test (`real_backend`-gated, mirrors this project's existing pipeline
      tests): `compute_mask(..., frame_range=(a, b))` end-to-end produces a full-volume-shaped
      result identical to an unbounded `compute_mask()` call within frames `[a, b]`, and is
      all-background outside that range — new file `tests/integration/test_frame_range.py`
      (C-PV-12)
- [X] T005 [P] Integration test (`real_backend`-gated): `InteractiveSession.export()` always
      performs a fresh whole-volume computation, even when `self._preview` currently holds a
      narrow `frame_range`-limited result from a prior `preview(frame_range=...)` call — extend
      `tests/integration/test_us6_interactive.py` (FR-008, C-PV-9)
- [X] T006 [P] Performance test (`real_backend`-gated, mirrors `tests/performance/
      test_benchmark.py`'s pattern): `compute_mask(..., frame_range=(f, f))` on a real volume
      completes in under 10 seconds (SC-001); `compute_mask(..., frame_range=(f-5, f+5))` shows
      comparable wall-clock time on two synthetic volumes of very different total depth, same
      window size (SC-002) — new file `tests/performance/test_frame_range_perf.py` (research R5,
      C-PV-13/14, Constitution Principle IV)
- [X] T007 [P] Unit test: `_PreviewBusyGuard.try_start()` returns `True` and marks busy when idle,
      returns `False` (no-op) when already busy; `finish()` clears busy state — in new file
      `tests/unit/test_interactive_preview_state.py` (research R4, FR-011)

### Implementation

- [X] T008 Add `frame_range: tuple[int, int] | None = None` to `RunConfig` with bounds validation
      in `__post_init__` (`0 <= start <= end`) in `src/ome_zarr_masker/config.py` (depends on
      T003 failing first) (data-model.md)
- [X] T009 Implement the pure `_crop_to_frame_range`/`_place_at_offset` helpers and wire
      `compute_mask` to use them when `config.frame_range` is set — crop the prompted-axis volume
      and remap prompts before calling the existing, unmodified `run_sweep`, then place its result
      back into a full-volume-shaped array — in `src/ome_zarr_masker/engine/pipeline.py`
      (depends on T001, T002 failing first; depends on T008) (research R3)
- [X] T010 Change `InteractiveSession.export()` to always call `self.preview(frame_range=None)`
      fresh rather than reusing any cached `self._preview`, so a prior partial preview can never be
      silently exported — in `src/ome_zarr_masker/interactive.py` (depends on T005 failing
      first; depends on T009) (FR-008, C-PV-9)
- [X] T011 Implement the pure `_PreviewBusyGuard` class (`try_start() -> bool`, `finish() -> None`)
      in `src/ome_zarr_masker/interactive.py` (depends on T007 failing first) (research R4,
      FR-011)

**Checkpoint**: `frame_range` is fully supported, tested, and benchmarked end-to-end; unset
behavior is byte-identical to before this feature (T004 covers both directions); export can no
longer export a partial result by accident; the busy-guard primitive is ready for US1/US2 to
consume.

---

## Phase 2: User Story 1 - Fast single-slice preview while placing prompts (Priority: P1) 🎯 MVP

**Goal**: A dedicated shortcut computes a mask for only the currently-viewed frame, asynchronously,
with a busy indicator, merging into the shared preview layer without disturbing other frames.

**Independent Test**: On a real, large volume, place a point on the current slice, trigger
single-slice preview, and confirm a result appears within seconds without freezing the UI
(quickstart.md Step 2).

- [X] T012 [US1] Add the single-slice shortcut in `launch()`: `@thread_worker`-decorated
      computation calling `self.preview(frame_range=(current, current))` (`current` from
      `viewer.dims.current_step` on the swept axis) on a background thread, guarded by
      `_PreviewBusyGuard` (T011) per FR-011 — in `src/ome_zarr_masker/interactive.py` (depends
      on T009, T010, T011) (FR-003, FR-010, FR-011, C-PV-2/5/6)
- [X] T013 [US1] Show a busy indicator (`viewer.status` text) for the async computation's
      duration, driven by the guard's state, cleared on completion or error — in
      `src/ome_zarr_masker/interactive.py` (depends on T012) (FR-010)
- [X] T014 [US1] Merge the single-slice result into the shared "preview" layer at only that one
      frame index (create it zero-filled at the full volume shape first if it doesn't exist yet),
      leaving every other frame's existing content unchanged — in
      `src/ome_zarr_masker/interactive.py` (depends on T012) (research R3, C-PV-11)
- [X] T015 [US1] Show a clear, actionable message when single-slice is triggered with no prompts on
      the current frame, mirroring the existing "at least one positive point or box required"
      validation — in `src/ome_zarr_masker/interactive.py` (depends on T012) (Acceptance
      Scenario 3)

**Checkpoint**: Single-slice mode fully functional and independently shippable — validate manually
via `quickstart.md` Step 2's single-slice bullets, and automatically via T006's benchmark.

---

## Phase 3: User Story 2 - Bounded few-slices preview for local propagation context (Priority: P2)

**Goal**: A second shortcut computes a mask across a fixed ±5-frame window (11 frames total)
centered on the current slice, using the same async/busy-flag/merge machinery as single-slice.

**Independent Test**: Trigger few-slices preview near the middle of a volume and confirm the result
reflects propagation across the bounded window, clipped correctly near a volume boundary
(quickstart.md Step 2).

- [X] T016 [US2] Unit test: `_clip_window(current, half_width, n_frames)` returns `(current -
      half_width, current + half_width)` in the middle of the volume, and clips to `[0, n_frames -
      1]` near either boundary — in `tests/unit/test_interactive_preview_state.py` (same file as
      T007) (research R4, FR-004)
- [X] T017 [US2] Implement the pure `_clip_window` helper in
      `src/ome_zarr_masker/interactive.py` (depends on T016 failing first) (research R4)
- [X] T018 [US2] Add the few-slices shortcut in `launch()`, reusing T012's async/`_PreviewBusyGuard`
      pattern: computes `self.preview(frame_range=_clip_window(current, 5, n_frames))` — in
      `src/ome_zarr_masker/interactive.py` (depends on T012, T009, T017) (FR-004, FR-009,
      FR-010, FR-011, C-PV-3/5/6)
- [X] T019 [US2] Merge the few-slices result into the shared preview layer at only the window's
      frame indices, reusing T014's merge logic — in `src/ome_zarr_masker/interactive.py`
      (depends on T014, T018) (research R3, C-PV-11)

**Checkpoint**: Few-slices mode functional — validate manually via `quickstart.md` Step 2's
window/clipping bullets, and automatically via T006's benchmark and T016's unit test.

---

## Phase 4: User Story 3 - Whole-volume preview with a cost confirmation (Priority: P3)

**Goal**: The existing whole-volume `p` behavior is preserved exactly, but gated behind an explicit
confirmation dialog so it can no longer be triggered by accident.

**Independent Test**: Trigger whole-volume preview and confirm a confirmation dialog appears before
any computation starts; declining leaves the current preview and session state unchanged
(quickstart.md Step 3).

- [X] T020 [US3] Add the whole-volume shortcut in `launch()`: show a
      `qtpy.QtWidgets.QMessageBox.question(...)` confirmation naming the cost/time implication
      before computing; declining runs no computation and leaves state unchanged — in
      `src/ome_zarr_masker/interactive.py` (depends on T009) (FR-005, FR-006, C-PV-4/8)
- [X] T021 [US3] On confirmation, run the existing whole-volume computation synchronously
      (`frame_range=None`, today's exact `p` behavior) and replace the entire shared preview
      layer's data — in `src/ome_zarr_masker/interactive.py` (depends on T020) (FR-005,
      C-PV-11's whole-volume replace clause)

**Checkpoint**: Whole-volume mode functional with its confirmation gate — validate manually via
`quickstart.md` Step 3.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Lint/format compliance and final acceptance walkthrough.

- [X] T022 [P] Run `ruff check src tests && ruff format --check src tests` and fix any violations
      introduced by T008-T021 (Constitution Principle I)
- [X] T023 Run the fast suite (`pytest -q`) and the full `real_backend` suite
      (`pytest -m real_backend -q`, e.g. via a Slurm job on a GPU partition given this project's
      HPC environment) and confirm green with no regressions (Constitution Principle II, T004-T007
      plus the pre-existing suite)
- [X] T024 Walk `specs/007-interactive-preview-modes/quickstart.md` Steps 1-5 end-to-end (Steps 1
      and 5 are already covered by T004/T006/T007/T016; Steps 2-4 are the manual GUI walkthroughs)
      to confirm acceptance (SC-001 through SC-005)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No prerequisite phase — start immediately. Blocks US1 and US2 (both
  need `frame_range` and `_PreviewBusyGuard`); US3 has no functional dependency on `frame_range`
  but shares `interactive.py` and benefits from T010's export-safety fix landing first.
- **User Story 1 (Phase 2)**: Depends on Foundational (T009, T010, T011). This is the MVP.
- **User Story 2 (Phase 3)**: Depends on Foundational (T009, T011) and reuses US1's threading
  scaffolding (T012) and merge logic (T014) — build after US1 in practice even though it's a
  separate story (disclosed dependency; see spec.md User Story 2).
- **User Story 3 (Phase 4)**: Depends on Foundational (T009) only — could be built in parallel with
  US1/US2 by a second implementer, since it doesn't touch `frame_range`, `_PreviewBusyGuard`, or
  the merge helper at all.
- **Polish (Phase 5)**: Depends on all desired user stories being complete.

### Within Foundational

- Tests T001-T007 are written FIRST and MUST fail before their corresponding implementation task.
- T008 (config field) has no code dependency on T009/T010/T011 but must land before T009.
- T009 (engine) depends on T001, T002, T008.
- T010 (export fix) depends on T005, T009.
- T011 (busy guard) depends only on T007 — independent of the engine work, could be implemented in
  parallel with T008/T009 by a second implementer.

### Parallel Opportunities

- T001, T002, T003, T004, T005, T006, T007 target independent/new files — write in parallel.
- T011 (busy guard) has no dependency on T008/T009/T010 and could be implemented in parallel with
  them.
- T022 (lint) can run in parallel with T023/T024 once T008-T021 land.
- US3 (T020, T021) has no code dependency on US1/US2 and could proceed in parallel with them if
  staffed separately — though all three stories edit `interactive.py`, so a single implementer
  should sequence them to avoid merge conflicts.

---

## Parallel Example: Foundational

```bash
# Tests, launched together (independent/new files):
Task: "Unit test for crop+remap helper in tests/unit/test_pipeline_frame_range.py (T001)"
Task: "Unit test for place-back helper in tests/unit/test_pipeline_frame_range.py (T002)"
Task: "Unit test for RunConfig.frame_range validation in tests/unit/test_config.py (T003)"
Task: "Integration test for compute_mask(frame_range=...) in tests/integration/test_frame_range.py (T004)"
Task: "Integration test for export() ignoring a cached partial preview in tests/integration/test_us6_interactive.py (T005)"
Task: "Performance test for SC-001/SC-002 in tests/performance/test_frame_range_perf.py (T006)"
Task: "Unit test for _PreviewBusyGuard in tests/unit/test_interactive_preview_state.py (T007)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Foundational (frame_range engine support, export-safety fix, busy guard,
   performance benchmark).
2. Complete Phase 2: User Story 1 (single-slice preview).
3. **STOP and VALIDATE**: run `quickstart.md` Step 2's single-slice bullets on a real large volume,
   and confirm T006's benchmark passes.
4. Ship — single-slice alone already fixes the reported bug for the most common workflow.

### Incremental Delivery

1. Foundational → frame_range, export safety, busy guard, and performance target all verified.
2. Add User Story 1 → validate → ship (MVP: fixes the core "preview doesn't display" bug).
3. Add User Story 2 → validate → ship (adds the local-context middle tier).
4. Add User Story 3 → validate → ship (restores whole-volume, now safely gated).
5. Each story adds value without breaking the previous ones.

---

## Notes

- [P] tasks = different files, no dependency on an incomplete task
- Verify T001-T007 fail before implementing T008-T011
- Commit after each task or logical group (e.g., T001-T007 together as the failing/red baseline,
  then T008, then T009, then T010 and T011 together — each landing green in turn; then each user
  story's tasks as their own commit(s))
- `launch()`'s genuinely display-dependent wiring (layers, keybinding registration, the
  confirmation dialog, `viewer.status`) has no automated test coverage (pre-existing project
  boundary, unchanged by this feature) — T012-T021's *display-dependent* parts are validated via
  `quickstart.md`'s manual walkthrough (T024); their *pure logic* (busy-guard, window-clip) is
  covered by T007/T016
