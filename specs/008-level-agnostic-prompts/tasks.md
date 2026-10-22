# Tasks: Level-Agnostic Prompt Coordinates

**Input**: Design documents from `/specs/008-level-agnostic-prompts/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/prompt-file-format.md, quickstart.md (all present)

**Tests**: Per Constitution Principle II (Test Discipline, NON-NEGOTIABLE), every behavioral change
MUST include automated tests, written to fail first. All test tasks below are REQUIRED, not optional.

**Organization**: Tasks are grouped by user story (spec.md) to enable independent implementation and
testing of each story, after a Setup/Foundational base that every story depends on.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1/US2/US3); Setup, Foundational, and Polish
  tasks carry no story label
- File paths are exact and repo-root-relative

## Path Conventions

Single project: `src/ome_zarr_masker/`, `tests/` at repository root (per plan.md).

---

## Phase 1: Setup (Shared Test Infrastructure)

**Purpose**: Test helpers needed before any failing test in later phases can be written.

- [X] T001 Add a `write_prompt_file(path, objects, level=0)` helper to `tests/conftest.py` that
  writes `{"level": level, "objects": objects}` as JSON -- the one place that constructs a
  new-format prompt file, used by Foundational and later test tasks instead of repeating the
  `json.dumps({...})` literal. *(Implemented, then removed before commit: each fixture file has its
  own local prompt-writing helper, so adding `"level"` in place was the smaller diff and the shared
  helper ended up with no callers.)*
- [X] T002 Add an optional `axis_factors: tuple[int, int, int] = (2, 2, 2)` parameter to
  `write_ome_zarr()` in `tests/conftest.py`: build each level by slicing
  `[::axis_factors[0], ::axis_factors[1], ::axis_factors[2]]` instead of the hardcoded `[::2, ::2,
  ::2]`; the default reproduces today's behavior exactly, so every existing caller is unaffected

**Checkpoint**: Test infrastructure ready for Foundational and User Story tests.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The `PromptSet.level` field, the shape-ratio conversion method, and the file-format
change are shared by all three user stories -- none of US1/US2/US3 is implementable without them.
This phase also fixes every existing test that hand-writes the now-outdated prompt-file format, since
leaving any of them broken would violate the full-suite-green gate for every later checkpoint.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Write failing unit tests in `tests/unit/test_prompts.py` for: `PromptSet.level` defaults
  to `None` when not passed; `PromptSet.to_record()` returns `{"level": ..., "objects": [...]}`
  (not a bare list) with `objects` holding today's per-prompt dicts unchanged
- [X] T004 Add `level: int | None = None` to the `PromptSet` dataclass and change
  `PromptSet.to_record()` to return `{"level": self.level, "objects": [existing per-prompt dicts]}`
  in `src/ome_zarr_masker/prompts/model.py` (makes T003 pass)
- [X] T005 [P] Update `InvocationLog.record_prompts()` in `src/ome_zarr_masker/input_log.py` to
  read `prompts.to_record()`'s new `{"level", "objects"}` shape (iterate `record["objects"]` instead
  of the old bare list) and emit one new `prompt_level: <value>` line; depends on T004
- [X] T006 Write failing unit tests in `tests/unit/test_prompts.py` for
  `PromptSet.resolved_for_shape(src_shape, dst_shape, axis_index)`: (a) identity -- returns the same
  object/values when `src_shape == dst_shape`; (b) isotropic conversion of `point_coords`, `box`,
  and `frame_index` when every axis scales by the same ratio; (c) anisotropic conversion -- the sweep
  axis (`axis_index`) and the two in-plane axes scale by different, independent ratios; (d) nearest-
  pixel rounding (half-pixel cases round, don't truncate)
- [X] T007 Implement `PromptSet.resolved_for_shape(src_shape, dst_shape, axis_index) -> PromptSet` in
  `src/ome_zarr_masker/prompts/model.py`: identity shortcut when shapes are equal; otherwise
  per-axis ratio scaling of `frame_index` (sweep axis), and `point_coords`/`box` (the two remaining
  axes, in the same height/width order `PromptSet.validate()` already uses), rounded to the nearest
  pixel (makes T006 pass)
- [X] T008 Write a failing unit test in `tests/unit/test_prompts.py`: `load_prompt_file()` raises
  `PromptError` with a clear message when the JSON has no top-level `"level"` key; parses `"level"`
  into `PromptSet.level` when present
- [X] T009 Update `load_prompt_file()` in `src/ome_zarr_masker/prompts/model.py` to require and
  parse the top-level `"level"` key (FR-007): raise `PromptError` when absent, otherwise set the
  returned `PromptSet.level` from it (makes T008 pass)
- [X] T010 [P] In `src/ome_zarr_masker/api.py`, change `predict()`'s
  `prompt_set = PromptSet(list(self._prompts))` to
  `PromptSet(list(self._prompts), level=self._level)` so the API path stamps its current level the
  same way the file format now requires; depends on T004 (needed now, not deferred to a later story,
  because `tests/integration/test_api_cli_parity.py` compares CLI and API run-records for equality --
  once T009 makes the CLI's prompt file carry a real `level`, the API side must carry the matching
  value or that existing parity test breaks)
- [X] T011 Add `"level"` to the two prompt-file JSON literals in `load_prompt_file`'s existing tests
  (`test_load_prompt_file_single_point`, `test_load_prompt_file_box`) in `tests/unit/test_prompts.py`
  so they keep passing under T009
- [X] T012 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_frame_range.py`
- [X] T013 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_log_cli_failure.py`
- [X] T014 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_log_cli_runid.py`
- [X] T015 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_log_cli.py`
- [X] T016 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_us5_postprocess.py`
- [X] T017 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_log_besteffort.py`
- [X] T018 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_us6_interactive.py`
- [X] T019 [P] Add a `"level"` matching each case's own `--level` argument to the `_prompts()` helper
  in `tests/integration/test_us3_levels.py` (its 3 existing tests use `--level 0`, the unspecified
  default/coarsest, and `--level 99`/invalid respectively -- use `0`, the actual coarsest index, and
  `0` in that order so each stays a same-level, non-converting case until Phase 3 adds the new
  cross-level cases)
- [X] T020 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_log_options.py`
- [X] T021 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_log_prompts_cli.py`
- [X] T022 [P] Add `"level": 0` to the prompt-file JSON fixture in
  `tests/integration/test_api_cli_parity.py` (matching its `--level 0` / `set_volume(level=0)`, so
  the parity assertion keeps holding under T010)
- [X] T023 [P] Add `"level"` to the prompt-file JSON fixture in `tests/integration/test_log_stdout_clean.py`
- [X] T024 [P] Add `"level"` to the prompt-file JSON fixture in `tests/contract/test_cli_mask.py`

**Checkpoint**: `PromptSet`/`load_prompt_file`/`to_record()` carry and expose the authoring level;
the full existing test suite is green again; user story implementation can now begin.

---

## Phase 3: User Story 1 - Rerun masking at a different level without re-authoring prompts (Priority: P1) 🎯 MVP

**Goal**: A prompt set authored (by coordinate value) against one pyramid level produces a correctly
located mask when the pipeline is actually run at a different level of the same input -- the bug this
whole feature exists to fix.

**Independent Test**: Author a prompt set against a coarse level, save it, rerun the masking pipeline
pointing at a finer level of the same input, and confirm the resulting mask targets the same
anatomical location as the coarse-level run (not a scaled-off location).

### Tests for User Story 1

> Write these first; confirm each fails against Phase 2's code (no conversion wired into the
> pipeline yet) before implementing T029.

- [X] T025 [US1] In `tests/integration/test_us3_levels.py`, write a failing test (marked
  `@pytest.mark.real_backend`, matching this file's existing tests):
  author a prompt file with `"level": 0` at level-0 coordinates (`single_blob_zarr`'s blob center),
  run `mask` with `--level` set to the coarsest level, and assert the output mask has foreground at
  the blob's coarsest-level location (spec Acceptance Scenario 1, contract C-PF-1)
- [X] T026 [US1] In `tests/integration/test_us3_levels.py`, write a failing test (`real_backend`): run
  the *same* prompt file/level combination twice (authoring level == run level) and assert the two
  output masks and run records are identical (ignoring `run_id`) -- the FR-006/SC-002 no-regression
  guard, at the integration level (contract C-PF-2)
- [X] T027 [US1] In `tests/integration/test_us3_levels.py`, write a failing test (`real_backend`): a
  point placed near the frame edge at a coarse authoring level, run at a much finer level, rounds to
  a pixel outside that finer level's bounds -- assert the existing out-of-bounds `PromptError`/CLI
  exit code 1 still fires rather than clamping silently (spec Edge Cases, contract C-PF-5)
- [X] T028 [US1] In `tests/integration/test_us3_levels.py`, write a failing test (`real_backend`) using
  T002's `axis_factors`: build a store where the sweep axis downsamples by one factor and the
  in-plane axes by a different factor between levels, author a prompt at one level, run at the other,
  and assert the mask is still correctly located (spec Acceptance Scenario 3, contract C-PF-6)

### Implementation for User Story 1

- [X] T029 [US1] In `compute_mask` (`src/ome_zarr_masker/engine/pipeline.py`), immediately after
  `level_shape = reader.level_shape(level)` and before `prompts.validate(level_shape,
  prompted_index)`, add: when `prompts.level` is not `None` and not equal to `level`, replace
  `prompts` with
  `prompts.resolved_for_shape(reader.level_shape(prompts.level), level_shape, prompted_index)`
  (implements T025-T028; depends on Foundational T007)

**Checkpoint**: User Story 1 is fully functional and independently testable/demoable -- a saved
prompt file (or API-built prompt set) authored at one level correctly relocates to any other level of
the same input. This is the MVP.

---

## Phase 4: User Story 2 - See which level a prompt was originally authored at (Priority: P2)

**Goal**: A researcher can see, in a saved prompt file or run record, which level each prompt set was
authored at, without reverse-engineering it from pixel values.

**Independent Test**: Author a prompt set at a known level, save it, open the saved file, and confirm
the originating level is recorded in a human-readable way.

**Note**: The mechanics (the `level` field, `to_record()`'s shape, and both entry points stamping it)
were already required to land in Phase 2 (T004/T005/T009/T010) because other code paths depend on
them unconditionally. This phase's job is the end-to-end proof that traceability is actually visible
to a user, for both entry points.

### Tests for User Story 2

- [X] T030 [P] [US2] In `tests/integration/test_log_prompts_cli.py`, write a failing test (marked
  `@pytest.mark.real_backend`, matching this file's existing tests): run `mask` via the CLI with a
  prompt file whose `"level"` is, say, `2`; assert the saved
  `run_record.json`'s `["prompts"]["level"] == 2` and the per-invocation input log contains
  `prompt_level: 2` (spec User Story 2 Acceptance Scenario 1, contract C-PF-7)
- [X] T031 [P] [US2] In `tests/integration/test_log_api.py`, write a failing test (`real_backend`):
  call `set_volume(..., level=2)` then `add_prompts(...)` then `predict()` via the API; assert the
  saved `run_record.json`'s `["prompts"]["level"] == 2`, matching what an equivalent CLI run would
  record (API/CLI parity, contract C-PF-7)

**Checkpoint**: Both tests pass without further production-code changes if Phase 2 was done
correctly; if either fails, the gap is in `prompts/model.py`, `input_log.py`, or `api.py` and must be
fixed before this story is considered done.

---

## Phase 5: User Story 3 - Clear error instead of silent misplacement when conversion isn't possible (Priority: P3)

**Goal**: Running a prompt set whose recorded authoring level doesn't exist in the current input's
pyramid fails clearly, instead of guessing a scale.

**Independent Test**: Load a prompt set whose recorded authoring level does not exist in the current
input's pyramid, run the pipeline, and confirm a clear, actionable error is raised.

### Tests for User Story 3

- [X] T032 [US3] In `tests/integration/test_us3_levels.py`, write a failing test: a prompt file with
  `"level": 99` (or any index `>= reader.n_levels`) run against an input whose pyramid doesn't have
  that many levels fails with exit code 1, an error message naming the available levels (reusing the
  existing "available levels" phrasing style from the current missing-`--level` test), and leaves no
  partial OUTPUT (spec User Story 3 Acceptance Scenario 1, contract C-PF-4)

### Implementation for User Story 3

- [X] T033 [US3] In `compute_mask` (`src/ome_zarr_masker/engine/pipeline.py`), immediately before
  the conversion call added in T029, add: when `prompts.level` is not `None` and not
  `0 <= prompts.level < reader.n_levels`, raise `PromptError` naming `prompts.level` and
  `reader.describe_levels()` (implements T032; depends on T029's insertion point existing)

**Checkpoint**: All three user stories are independently functional and tested.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation alignment and the feature's performance budget (plan.md Technical Context).

- [X] T034 [P] Update the prompt-file JSON example in `README.md` to include the required `"level"`
  field
- [X] T035 [P] Update the `Prompt`/`PromptSet` entity tables in
  `specs/001-ome-zarr-sam-masking/data-model.md` and the prompt-file-format example in
  `specs/001-ome-zarr-sam-masking/contracts/cli.md` to match the schema in this feature's
  `data-model.md`/`contracts/prompt-file-format.md`
- [X] T036 In `tests/unit/test_prompts.py`, add a timing assertion: converting a 10,000-prompt
  `PromptSet` via `resolved_for_shape` completes in under 1 ms (plan.md's declared performance
  budget, Constitution Principle IV)
- [X] T037 Run `specs/008-level-agnostic-prompts/quickstart.md`'s five validation scenarios end-to-end
  and confirm each matches its documented expected outcome
- [X] T038 Full-suite regression pass: `pytest -q` (and `-m real_backend` where the SAM2 backend is
  available) green, with no unexpected skips beyond the existing SAM2-availability guard

---

## Phase 7: Rework to physical mapping (2026-10-16, aligned with feature 009)

**Purpose**: Replace the shape-ratio conversion with the physical mapping chosen in
`specs/009-scalable-mask-writer` (spec Clarifications, research R8), so prompts and the written mask
use one rule.

- [X] T039 Write failing unit tests in `tests/unit/test_geometry.py` for
  `geometry.nearest_index(coords, from_scale, from_translation, to_scale, to_translation)`: identity,
  ×2 down/up-sampling, ties to the lower index, a brute-force nearest-centre check on the real DANDI
  001278 level-3 → level-0 transforms, int64 and unclipped output
- [X] T040 Write failing unit tests in `tests/unit/test_reader.py` for
  `OmeZarrReader.level_transform(level)`: translation defaults to zeros on the existing fixture; scale
  and translation are read from a store with explicit translations
- [X] T041 Rewrite the conversion unit tests in `tests/unit/test_prompts.py` against
  `PromptSet.resolved_between(src_geometry, dst_geometry, axis_index)`: identity, isotropic,
  sweep-axis independence, height/width independence, nearest-pixel rounding, exact tie to the lower
  pixel (x = 15 → 7, in bounds), half-pixel translations in both directions, out-of-bounds result
  still rejected by `validate()`, level preserved, 500-prompt performance budget
- [X] T042 Rework `test_out_of_bounds_after_conversion_still_raises` in
  `tests/integration/test_us3_levels.py`: monkeypatch `OmeZarrReader.level_transform` to shift the run
  level's translation so a correctly authored point maps out of bounds, and assert exit 1 with no
  output (no SAM2 needed; the old version relied on a round-half-to-even artifact)
- [X] T043 Add `src/ome_zarr_masker/geometry.py::nearest_index` and
  `src/ome_zarr_masker/io/reader.py::OmeZarrReader.level_transform` (makes T039–T040 pass)
- [X] T044 Replace `PromptSet.resolved_for_shape` with `PromptSet.resolved_between` in
  `src/ome_zarr_masker/prompts/model.py` (vectorised: one `nearest_index` call per axis across all
  prompts; `Prompt.__new__` bypass kept) and call it from `src/ome_zarr_masker/engine/pipeline.py`
  with `reader.level_transform(prompts.level)` / `reader.level_transform(level)` (makes T041–T042 pass)
- [X] T045 Update this feature's spec (Clarifications, FR-004, Edge Cases, Assumptions), research (R8;
  R1/R3 marked superseded), data-model, contract (C-PF-5/6), plan and quickstart; full regression
  green (`ruff check src tests`, `ruff format --check src tests`, `pytest -q`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies -- start immediately.
- **Foundational (Phase 2)**: Depends on Setup (T001/T002's helpers are used by several Foundational
  tasks) -- BLOCKS all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational completion. No dependency on US2/US3.
- **User Story 2 (Phase 4)**: Depends on Foundational completion only (its mechanics already landed
  there) -- independent of US1/US3, though it can't be *demonstrated* meaningfully until US1 also
  makes cross-level runs actually work.
- **User Story 3 (Phase 5)**: Depends on Foundational completion *and* on US1's T029 (shares the same
  insertion point in `compute_mask`) -- the one deliberate exception to story independence, noted in
  plan.md/research.md as both edits landing in the same function.
- **Polish (Phase 6)**: Depends on US1 + US2 + US3 all complete.

### Within Each Phase

- Tests are written and confirmed failing before their corresponding implementation task.
- Foundational tasks that touch the same file (`tests/unit/test_prompts.py`:
  T003/T006/T008/T011; `src/ome_zarr_masker/prompts/model.py`: T004/T007/T009) are sequential
  within that file, even where no logical dependency exists between the specific tests.

### Parallel Opportunities

- T001/T002 are sequential (same file).
- Within Foundational: T005 and T010 can run in parallel (different files: `input_log.py` vs.
  `api.py`; both depend only on T004). T012-T024 (13 distinct test files) can all run in parallel
  with each other, with T005, and with T010, once T009 has landed.
- Within User Story 2: T030 and T031 can run in parallel (different files).
- Within Polish: T034 and T035 can run in parallel (different files).

---

## Parallel Example: Foundational mechanical fixture fixes

```bash
# After T009 (load_prompt_file requires "level") lands, these 13 are independent:
Task: "Add \"level\" to the prompt-file JSON fixture in tests/integration/test_frame_range.py"
Task: "Add \"level\" to the prompt-file JSON fixture in tests/integration/test_log_cli_failure.py"
Task: "Add \"level\" to the prompt-file JSON fixture in tests/integration/test_log_cli_runid.py"
Task: "Add \"level\" to the prompt-file JSON fixture in tests/integration/test_log_cli.py"
# ... (T016-T024 similarly)
```

## Parallel Example: User Story 2

```bash
Task: "Integration test: CLI run_record.json + input log show the authoring level (test_log_prompts_cli.py)"
Task: "Integration test: API run_record.json shows the authoring level, matching CLI (test_log_api.py)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (the field, the conversion method, the file-format change, and
   fixing every existing test the change touches).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: run `tests/integration/test_us3_levels.py -m real_backend`; confirm a prompt
   authored at one level correctly locates the target at another level.
5. This is already the feature's core value -- US2/US3 add traceability and a safety net around it.

### Incremental Delivery

1. Setup + Foundational -> suite green, nothing user-visible changed yet except the now-required
   `"level"` field in prompt files.
2. Add User Story 1 -> cross-level reuse works (MVP).
3. Add User Story 2 -> traceability is visible end-to-end for both CLI and API.
4. Add User Story 3 -> unknown authoring levels fail clearly instead of silently.
5. Polish -> docs aligned, performance budget asserted, quickstart re-validated.

---

## Notes

- [P] tasks touch different files and have no incomplete dependency between them.
- Story labels (US1/US2/US3) map 1:1 to spec.md's three user stories; Setup/Foundational/Polish carry
  none, per the task-format rule.
- Tasks noting `real_backend` mark the new test `@pytest.mark.real_backend`, matching this repo's
  existing convention for tests requiring a constructable SAM2 backend (skipped otherwise).
- Commit after each task or small logical group, per plan.md's atomic-commit grouping; Constitution
  Principle III applies throughout.
- T011-T024's "add `level`" edits are intentionally small and mechanical -- resist the urge to
  refactor the surrounding test while touching it; that is out of scope for this feature.
