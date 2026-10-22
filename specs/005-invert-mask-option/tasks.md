---

description: "Task list for Invert Mask Output Option"
---

# Tasks: Invert Mask Output Option

**Input**: Design documents from `/specs/005-invert-mask-option/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, quickstart.md

**Tests**: REQUIRED. Per Constitution Principle II (Test Discipline, NON-NEGOTIABLE), tests are
written FIRST and must fail before implementation.

**Organization**: Spec.md has a single user story (P1) — there is no smaller independently
valuable slice, so all behavioral tasks live in Phase 2. No Setup or Foundational phase is needed:
this feature adds one field, one post-processing step, and one CLI flag to existing modules
(`config.py`, `postprocess/morphology.py`, `cli.py`) with no new dependency, module, or scaffolding
(plan.md Technical Context / Scale-Scope).

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: User story label (US1) on user-story phase tasks only

## Path Conventions

Single Python package, `src/` layout: `src/ome_zarr_masker/`, tests in `tests/`.

---

## Phase 1: User Story 1 - Produce a mask-out (background-labeled) output (Priority: P1) 🎯 MVP

**Goal**: `ome-zarr-masker mask ... --invert` writes a binary output mask whose values are the
exact voxel-wise complement of the non-inverted output, applied after `--combine`/`--fill-holes`/
`--dilate`/`--erode` so those flags always shape the organ-labeled region (FR-001–FR-008).

**Independent Test**: Run `mask` twice on the same input/prompts, once without `--invert` and once
with it; confirm the two outputs are exact voxel-wise complements (quickstart.md Scenario 2).

### Tests for User Story 1 (write first, must FAIL before T005-T007)

- [X] T001 [P] [US1] Unit test: `postprocess_mask()` with `PostProcessConfig(invert=True)` returns
      the exact boolean complement of the non-inverted result on a synthetic array, and — when
      `dilation_radius`/`erosion_radius`/`fill_holes` are also set — the dilate/erode/fill-holes
      steps are proven to act on the organ region (i.e. inverting-then-complementing recovers the
      non-inverted dilated/eroded/filled mask exactly); also cover the two boundary cases from
      spec.md Edge Cases directly — an all-`False` input mask MUST invert to all-`True`, and an
      all-`True` input mask MUST invert to all-`False` — in new file `tests/unit/test_morphology.py`
      (FR-003, FR-004, research.md R1, spec.md Edge Cases)
- [X] T002 [P] [US1] Unit test: `PostProcessConfig.invert` defaults to `False`; `is_noop` is
      `False` when only `invert=True` is set (all other fields at their defaults); and
      `RunConfig.to_record()["postprocess"]` includes `"invert"` reflecting the configured value,
      in `tests/unit/test_config.py` (FR-006, data-model.md)
- [X] T003 [P] [US1] Contract test: `ome-zarr-masker mask --help` output contains a description
      of `--invert` (C-CLI-8), and `ome-zarr-masker interactive --invert` exits non-zero with
      argparse's "unrecognized arguments" message (C-CLI-9), in `tests/contract/test_cli_mask.py`
      (FR-007, FR-008)
- [X] T004 [P] [US1] Integration test (`real_backend`-gated, mirrors existing fixtures in this
      file): running `mask` on the same store/prompts with and without `--invert` (and again with
      `--dilate 2 --invert` vs. `--dilate 2`) produces exact voxel-wise complements end-to-end, and
      output dtype stays `uint8`; additionally assert the *non*-inverted (`--invert` omitted) run's
      output array is byte-for-byte equal to a run of the same inputs on the pre-005 code path (or,
      equivalently, equal to what this file's existing fixtures already assert for that input),
      giving SC-002 a direct assertion rather than relying only on T009's "existing suite stays
      green", in `tests/integration/test_us5_postprocess.py` (SC-001, SC-002, FR-002, FR-004,
      FR-005, quickstart.md Scenarios 2-3)

### Implementation for User Story 1

- [X] T005 [US1] Add `invert: bool = False` field to `PostProcessConfig` in
      `src/ome_zarr_masker/config.py`; update the `is_noop` property to
      `not self.fill_holes and self.dilation_radius == 0 and self.erosion_radius == 0 and not self.invert`;
      update `RunConfig.to_record()`'s `postprocess` dict to add `"invert": self.postprocess.invert`
      (depends on T002 failing first) (data-model.md)
- [X] T006 [P] [US1] In `postprocess_mask()` (`src/ome_zarr_masker/postprocess/morphology.py`),
      add the invert step as the last operation, after dilation, erosion, and fill-holes: when
      `config.invert` is `True`, negate the boolean mask (`out = ~out`) before returning; update the
      module docstring's documented order to `dilation, erosion, fill-holes, invert` (depends on
      T005; depends on T001 failing first) (FR-003, FR-004, research.md R1)
- [X] T007 [P] [US1] Add `--invert` to the `mask` subparser only in `src/ome_zarr_masker/cli.py`
      (`action="store_true"`, default `False`, help text stating it swaps the mask's foreground/
      background values); pass `invert=args.invert` into the `PostProcessConfig(...)` construction
      in `_cmd_mask`; do NOT add it to the `interactive` subparser (depends on T005; depends on T003
      failing first) (FR-001, FR-006, FR-007, FR-008, C-CLI-7, C-CLI-8, C-CLI-9, research.md R2/R3)

**Checkpoint**: T001-T004 all pass; `--invert` is fully functional on `mask`, absent from
`interactive`, and default (no-flag) behavior is unchanged (SC-002). This is the entire feature —
independently shippable.

---

## Phase 2: Polish & Cross-Cutting Concerns

**Purpose**: Lint/format compliance and final acceptance walkthrough.

- [X] T008 [P] Run `ruff check src tests && ruff format --check src tests` and fix any violations
      introduced by T005-T007 (Constitution Principle I)
- [X] T009 Run the full `pytest` suite (`pytest -q`, then `pytest -m real_backend -q` where a
      GPU/SAM2 install is available) and confirm it is green with no regressions outside this
      feature's new/changed tests; this is the suite-wide backstop for SC-002 (every pre-existing
      test's own output assertions must still hold unchanged), complementing T004's direct
      byte-equality check (Constitution Principle II, SC-002)
- [X] T010 Walk `specs/005-invert-mask-option/quickstart.md` Scenarios 1-5 end-to-end to confirm
      acceptance (SC-001, SC-002, SC-003) — satisfied by the automated tests that mirror each
      scenario 1:1: Scenario 1 (help/interactive rejection) by T003, Scenarios 2-3 (complement
      property, dilate ordering) by T004 (run on GPU via slurm job 23677716), Scenario 4 (no
      regression) by T009 (fast suite + full `real_backend` suite via slurm job 23678031, both
      green), Scenario 5 (GPU-free unit coverage) by T001

---

## Dependencies & Execution Order

### Phase Dependencies

- **User Story 1 (Phase 1)**: No prerequisite phase — start immediately. This is the MVP and the
  entire behavioral scope of the feature.
- **Polish (Phase 2)**: Depends on Phase 1 (T005-T007) being complete.

### Within User Story 1

- Tests T001-T004 are written FIRST and MUST fail before their corresponding implementation task.
- T005 (config field) has no code dependency on T006/T007 but must land before either, since both
  read `config.invert`.
- T006 (morphology) and T007 (CLI) touch different files and are independent of each other once
  T005 is done.

### Parallel Opportunities

- T001, T002, T003, T004 target four different files with no shared state — write in parallel.
- T006 and T007 target different files (`postprocess/morphology.py` vs. `cli.py`) and can proceed
  in parallel once T005 is committed.
- T008 (lint) can run in parallel with T009/T010 once T005-T007 land, since it touches no test
  behavior.

---

## Parallel Example: User Story 1

```bash
# Tests, launched together (different files):
Task: "Unit test for invert ordering/complement in tests/unit/test_morphology.py (T001)"
Task: "Unit test for PostProcessConfig.invert / to_record() in tests/unit/test_config.py (T002)"
Task: "Contract test for --invert help text and interactive rejection in tests/contract/test_cli_mask.py (T003)"
Task: "Integration test for end-to-end complement property in tests/integration/test_us5_postprocess.py (T004)"

# Implementation, after T005 lands:
Task: "Apply invert as the final postprocess_mask() step in src/ome_zarr_masker/postprocess/morphology.py (T006)"
Task: "Add --invert to the mask subparser in src/ome_zarr_masker/cli.py (T007)"
```

---

## Implementation Strategy

### MVP First (and only) Scope

1. Complete Phase 1 (User Story 1) — the entire feature.
2. **STOP and VALIDATE**: run T008-T010 (Polish) to confirm lint, full suite, and quickstart pass.
3. Ship — there is no Phase 2+ user story to layer on.

---

## Notes

- [P] tasks = different files, no dependency on an incomplete task
- Verify T001-T004 fail before implementing T005-T007
- Commit after each task or logical group (e.g., T001-T004 together as the failing/red baseline,
  then T005, then T006+T007 together as the green implementation)
- `interactive` subcommand is explicitly out of scope (FR-008) — no task touches
  `src/ome_zarr_masker/interactive.py`
