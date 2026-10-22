---

description: "Task list for Interactive Prompt Layers (Points + Box)"
---

# Tasks: Interactive Prompt Layers (Points + Box)

**Input**: Design documents from `/specs/006-interactive-prompt-layers/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/interactive-ui.md,
quickstart.md

**Note**: This tasks.md was generated after implementation (the conversation moved directly from
`/speckit-plan` into the feature 007 preview-bug investigation before `/speckit-tasks` ran for this
feature). It documents the actual work done, in the same format as the other features' task lists,
so the spec-kit trail stays complete.

**Tests**: REQUIRED for the headless core (Principle II) -- box bookkeeping is fast/GPU-free
(`OrganMaskPredictor.set_volume` needs no real backend); merged points+box prompts and CLI parity
are `real_backend`-gated. `launch()`'s GUI wiring (layers, keybindings, box-layer enforcement,
active-layer auto-clear) carries the pre-existing `# pragma: no cover` boundary and has no
committed automated test, but was verified during implementation via an ad hoc offscreen napari
smoke test (`QT_QPA_PLATFORM=offscreen`) covering layer styling, `n`/`y` flip + continuity,
active-layer auto-clear, box duplicate-frame replacement, and non-rectangle rejection -- not
committed as a permanent test, consistent with this project's established GUI-testing boundary.

**Organization**: Tasks are grouped by user story per spec.md's two stories (US1 points, US2 box).

## Format: `[ID] [P?] [Story?] Description`

## Path Conventions

Single Python package, `src/` layout: `src/ome_zarr_masker/`, tests in `tests/`.

---

## Phase 1: Foundational (blocking prerequisite for both stories)

- [X] T001 Add `box: np.ndarray | None = None` (keyword-only) to
      `OrganMaskPredictor.add_prompts` in `src/ome_zarr_masker/api.py`, threaded into the single
      `Prompt` it constructs; `add_box` unchanged (research R2)
- [X] T002 Update `test_c_api_7_argument_names_and_shapes_match_sam2` in
      `tests/contract/test_python_api.py` for `add_prompts`'s new `box` parameter (caught as a
      regression when the fast suite was re-run after T001)
- [X] T003 Add `_boxes: dict[int, np.ndarray]` state plus `add_box`/`clear_boxes` methods to
      `InteractiveSession` in `src/ome_zarr_masker/interactive.py` (data-model.md)
- [X] T004 Rewrite `InteractiveSession.preview()`'s prompt-building loop to iterate the union of
      frames-with-points and frames-with-a-box, calling `add_prompts(..., box=...)` once per frame
      (research R2) in `src/ome_zarr_masker/interactive.py`

**Tests** (fast, GPU-free):

- [X] T005 [P] Unit-level test: `add_box` replaces any existing box for the same frame;
      `clear_boxes` empties it -- `tests/integration/test_us6_interactive.py::
      test_add_box_replaces_existing_box_for_same_frame` (no `real_backend` marker needed --
      `set_volume` doesn't touch SAM2)

**Tests** (`real_backend`-gated):

- [X] T006 [P] Integration test: a box-only prompt (no points) reaches the masking engine via
      `OrganMaskPredictor.add_box`'s path -- `test_box_only_prompt_reaches_the_masking_engine`
- [X] T007 [P] Integration test (SC-004/C-UI-15): a point + box on the same frame via
      `InteractiveSession` produces a mask identical to an equivalent CLI prompt-file with both --
      `test_interactive_point_and_box_match_equivalent_cli_prompt`

**Checkpoint**: Headless core supports box prompts, merged correctly with points per frame; the
engine change is byte-compatible for every existing `add_prompts` caller (default `box=None`).

---

## Phase 2: User Story 1 - Place and flip point prompts across dedicated layers (Priority: P1)

- [X] T008 [US1] Replace the single `"prompts"` points layer with two layers in `launch()`:
      `positive-points` (cross, size 7, lime, `border_width=0`) and `negative-points` (disc,
      size 6, red, `border_width=0`) -- FR-001/002/005/006, C-UI-1/2/3/4
- [X] T009 [US1] Implement `_flip_selected(source, dest)`: move `source.selected_data` to `dest`
      via `Points.remove_selected()` + `Points.add()` (whose own auto-select behavior satisfies
      FR-004b's post-flip continuity for free) -- bind `n`→positive→negative,
      `y`→negative→positive at the viewer level, not per-layer (FR-003/004, C-UI-7/8/9/12)
- [X] T010 [US1] Implement active-layer-change auto-clear: track the previously-active layer via a
      `nonlocal`, and on `viewer.layers.selection.events.active`, clear the outgoing layer's
      `selected_data` if it's one of the two point layers (FR-004a, C-UI-11)
- [X] T011 [US1] Update `_sync_points_from_layer` to read both point layers (positive → label 1,
      negative → label 0) into `self._points` (FR-009 point-side, C-UI-13)

**Checkpoint**: Verified via offscreen smoke test -- point placed in positive layer (auto-selected,
per napari's own `Points.add`), `n` moves it to negative (now selected there), `y` moves it back;
switching active layer to `negative-points` while `positive-points` still held a selection cleared
that stale selection, confirmed via `viewer.layers.selection.active = <layer>` in the smoke test.

---

## Phase 3: User Story 2 - Draw a positive box prompt (Priority: P2)

- [X] T012 [US2] Add the `positive-box` `Shapes` layer in `launch()`: `blending=
      "translucent_no_depth"`, `opacity=1.0`, `edge_color="lime"`, `edge_width=1`,
      `face_color="#00000000"` (FR-008, C-UI-6)
- [X] T013 [US2] Implement `_enforce_box_layer_rules`, connected to `box_layer.events.data`:
      remove any non-rectangle shape, and keep only the newest rectangle per frame (FR-007/010,
      C-UI-5). **Deferred via `QTimer.singleShot(0, ...)`** rather than mutating the layer
      synchronously inside its own `data`-event handler -- doing so recurses into napari/Qt's
      internal layer-change machinery and hits Python's recursion limit (discovered and fixed
      during implementation via the offscreen smoke test; not predicted by the plan).
- [X] T014 [US2] Add `_sync_boxes_from_layer`, deriving each rectangle's frame from its vertices'
      shared z-coordinate and its `[x0, y0, x1, y1]` extent from the min/max of the other two axes;
      combine with `_sync_points_from_layer` into `_sync_prompts_from_layers`, used by every
      preview/export trigger (`s`/`f`/`p`/`e`) (C-UI-13/14)
- [X] T015 [US2] Update the "no prompts on requested frame(s)" guard (feature 007's
      `_run_async_preview`) to also count a box on that frame, not just points -- a box-only
      single-slice/few-slices preview must not be rejected as "no prompts"

**Checkpoint**: Verified via offscreen smoke test -- drawing two rectangles on the same frame
leaves only the newest (`len(box.data)` 2 → 1 after the deferred fix runs); drawing an ellipse is
removed entirely (`shape_type` list back to just `["rectangle"]` or empty).

---

## Phase 4: Polish & Cross-Cutting Concerns

- [X] T016 [P] `ruff check src tests && ruff format --check src tests` -- clean
- [X] T017 Fast suite green (96 passed, 1 unrelated skip, no regressions); `real_backend` suite
      run via Slurm on `mit_normal_gpu` (job 23692113, 39 passed in 157s, no regressions)
- [X] T018 Manual GUI walkthrough: `quickstart.md`'s automatable scenarios are covered by
      T005-T007; the visual-appearance/keybinding-feel scenarios need an actual display, which
      this environment doesn't have -- unverified by a human, same caveat as feature 007's T024

---

## Notes

- No Setup/Foundational-vs-Setup split beyond Phase 1 above -- this is a small enough feature
  (2 user stories, one primary file) that a separate Setup phase would be empty.
- `interactive_output.ome.zarr` (a stray artifact from an earlier ad hoc `launch()` run predating
  this session) remains untracked in the repo root; unrelated to this feature, not touched.
