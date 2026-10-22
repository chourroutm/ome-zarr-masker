---
description: "Task list for Bundled OME-Zarr Validation Dependency"
---

# Tasks: Bundled OME-Zarr Validation Dependency

**Input**: Design documents from `/specs/003-bundled-ome-zarr-validation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/validation.md, quickstart.md

**Tests**: REQUIRED. Per Constitution Principle II (Test Discipline, NON-NEGOTIABLE), behavioral
tests are written FIRST and must fail before implementation.

**Organization**: Tasks are grouped by user story. This feature changes only how the existing
`io/validate.py` gate is implemented (in-process via `ome-zarr-models` instead of a subprocess on
`PATH`); the public `validate_ome_zarr(path) -> None` / `ValidationError` contract is unchanged.
Tests reuse feature 001's synthetic OME-Zarr fixture (`tests/conftest.py::write_ome_zarr`).

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: User story label (US1..US3) on user-story phases only

## Path Conventions

Single Python package, `src/` layout: `src/ome_zarr_masker/`, tests in `tests/`.

---

## Phase 1: Setup

**Purpose**: Confirm the validation dependency is declared with a reproducible floor (FR-007). This
is the only shared prerequisite; there is no separate Foundational phase.

- [X] T001 Confirm `ome-zarr-models>=1.6` (alongside `zarr>=3`) in `pyproject.toml` and verify the public symbols this feature uses (`ome_zarr_models.open_ome_zarr`, `ome_zarr_models.exceptions.ValidationWarning`) exist at the declared floor; raise the floor only if they are absent (FR-007)

**Checkpoint**: The in-process validation API is guaranteed available from a plain install.

---

## Phase 2: User Story 1 - Validate inputs after a plain install (Priority: P1) MVP

**Goal**: Input validation runs in-process from the installed `ome-zarr-models` package, so a valid
store validates with no separate install and no validator command on `PATH`; invalid/missing stores
and a missing dependency still fail with clear, actionable `ValidationError` messages.

**Independent Test**: With no `ome-zarr-models` command reachable on `PATH`, validate a known-valid
synthetic OME-Zarr v0.5 store (passes) and an invalid/missing store (rejected) — see
[quickstart.md](./quickstart.md) Scenarios 1 and 3.

### Tests for User Story 1 (write first, must FAIL before T005)

- [X] T002 [P] [US1] Unit test: a valid store validates with no `ome-zarr-models` command on `PATH` (monkeypatch `PATH`/`shutil.which` to None) and `validate_ome_zarr` returns without raising, in `tests/unit/test_validate.py` (C-VAL-1)
- [X] T003 [P] [US1] Unit test: validation spawns no child process — patch `subprocess.run`/`subprocess.Popen` to raise and assert both a valid and an invalid store complete via the in-process path, in `tests/unit/test_validate.py` (C-VAL-2)
- [X] T004 [P] [US1] Unit test: when `ome-zarr-models` cannot be imported, `validate_ome_zarr` raises `ValidationError` whose message names `ome-zarr-models` and how to install it (simulate the import failure), in `tests/unit/test_validate.py` (C-VAL-5)

### Implementation for User Story 1

- [X] T005 [US1] Rewrite `src/ome_zarr_masker/io/validate.py` to validate in-process: keep the missing-path check, then call `ome_zarr_models.open_ome_zarr(path, version="0.5")` inside `warnings.catch_warnings(action="error", category=ValidationWarning)`, mapping any failure to `ValidationError("input is not a valid OME-Zarr v0.5 store: ...")` and a failed `import ome_zarr_models` to an actionable `ValidationError` (FR-005); remove the `subprocess`/`shutil.which`/interpreter-adjacent path probing. Existing valid/invalid/missing tests in `tests/unit/test_validate.py` MUST stay green (C-VAL-3, C-VAL-4, C-VAL-6) (depends on T002, T003, T004)

**Checkpoint**: Validation works from a plain install with no `PATH` prerequisite; the full existing
suite is green. This is the MVP and independently shippable.

---

## Phase 3: User Story 2 - Accurate setup documentation (Priority: P2)

**Goal**: Project documentation no longer instructs users to put a validator command on `PATH` and
states that validation is provided by the installed package.

**Independent Test**: `grep -rni "validate.*on .*PATH\|CLI on .PATH" README.md specs/` returns no
user-facing prerequisite (quickstart.md Scenario 5).

- [X] T006 [P] [US2] Update `README.md`: in the Features list and Install section, remove the "`ome-zarr-models validate` CLI on `PATH`" prerequisite and state that OME-Zarr v0.5 validation is provided in-process by the installed `ome-zarr-models` package (FR-006, SC-004)
- [X] T007 [P] [US2] Align the remaining stale "validate CLI on PATH" references so no instruction requires a validator command on `PATH`: `specs/001-ome-zarr-sam-masking/quickstart.md`, `specs/001-ome-zarr-sam-masking/data-model.md`, and `specs/001-ome-zarr-sam-masking/contracts/python-api.md` (note the in-process change; do not rewrite historical decision records beyond the PATH prerequisite) (FR-006, SC-004)

**Checkpoint**: Documentation matches the new behavior; SC-004 (zero on-`PATH` instructions) holds.

---

## Phase 4: User Story 3 - Predictable validation regardless of environment (Priority: P3)

**Goal**: A conflicting or differently-versioned `ome-zarr-models` command on `PATH` does not affect
validation, because validation uses the in-process package dependency.

**Independent Test**: Place a broken/conflicting `ome-zarr-models` executable earlier on `PATH` and
confirm a valid store still validates and the on-`PATH` command is never invoked.

- [X] T008 [P] [US3] Unit test: with a fake/broken `ome-zarr-models` executable placed earlier on `PATH`, a valid store still validates and an invalid store is still rejected (the on-`PATH` command is never consulted), in `tests/unit/test_validate.py` (US3 acceptance, reinforces C-VAL-2)

**Checkpoint**: Validation behavior is independent of any on-`PATH` command (depends on T005).

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Performance evidence (Constitution IV) and end-to-end validation.

- [X] T009 [P] Performance test: `validate_ome_zarr` on the synthetic valid store completes under budget (< 500 ms, best-of-N) and spawns no sub-process, in `tests/performance/test_validate_perf.py` (C-VAL-7, SC-005)
- [X] T010 Run `ruff check src tests && ruff format --check src tests` and the full `pytest` suite green, then walk `specs/003-bundled-ome-zarr-validation/quickstart.md` Scenarios 1-5 to confirm acceptance

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - start immediately.
- **User Story 1 (Phase 2)**: Depends on Setup. This is the MVP and the behavioral core.
- **User Story 2 (Phase 3 - docs)**: Depends only on the behavior decided in US1; can be written
  in parallel with US1 implementation once the approach is fixed, but should land after T005.
- **User Story 3 (Phase 4)**: Depends on T005 (in-process implementation in place).
- **Polish (Phase 5)**: Depends on US1 (T005) complete.

### User Story Dependencies

- **US1 (P1)**: Independent; delivers the whole behavioral value on its own.
- **US2 (P2)**: Documentation-only; independently verifiable via grep, no code dependency beyond
  reflecting US1's decision.
- **US3 (P3)**: Verifies an invariant guaranteed by US1's in-process design; test-only.

### Within User Story 1

- Tests T002, T003, T004 are written FIRST and MUST fail before T005.
- T005 implements the change and turns all of them (and the pre-existing tests) green.

### Parallel Opportunities

- T002, T003, T004 target the same test file (`tests/unit/test_validate.py`); write them in one
  pass or sequentially to avoid edit conflicts even though they are logically independent.
- T006 and T007 (docs) are different files and can run in parallel.
- T009 is a new file and can be written in parallel with the docs tasks.

---

## Parallel Example: User Story 2

```bash
# Documentation updates touch different files and can proceed together:
Task: "Update README.md to drop the on-PATH prerequisite (T006)"
Task: "Align feature-001 spec references to remove on-PATH instructions (T007)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (confirm dependency floor).
2. Write failing tests T002-T004, then implement T005.
3. **STOP and VALIDATE**: full suite green; valid store validates with no validator on `PATH`.
4. Ship — the on-`PATH` prerequisite is eliminated.

### Incremental Delivery

1. Setup -> US1 (MVP, behavioral fix) -> commit.
2. US2 (docs) -> commit.
3. US3 (invariant test) + Polish (perf + quickstart) -> commit.
   Each commit stays green per Constitution Principle III.

---

## Notes

- [P] tasks = different files, no dependencies.
- Keep the public contract (`validate_ome_zarr(path) -> None`, raising only `ValidationError`)
  unchanged so the reader, pipeline, CLI, and API need no edits.
- Verify tests fail before implementing (Principle II).
- Commit after each task or logical group; keep each commit green (Principle III).
- No emojis in code, comments, or commit messages.
