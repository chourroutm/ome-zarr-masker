---
description: "Task list for Logging of Prompt and CLI Inputs"
---

# Tasks: Logging of Prompt and CLI Inputs

**Input**: Design documents from `/specs/002-input-logging/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED. Per Constitution Principle II (Test Discipline, NON-NEGOTIABLE), behavioral
tests are written FIRST and must fail before implementation.

**Organization**: Tasks are grouped by user story. This feature extends feature 001's package
(CLI, API, `RunConfig`, `PromptSet`, output run-record); tests use feature 001's synthetic OME-Zarr
fixture and stub backend.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: User story label (US1..US3) on user-story phases only

## Path Conventions

Single Python package, `src/` layout: `src/ome_zarr_masker/`, tests in `tests/`.

---

## Phase 1: Setup

**Purpose**: Module placeholder and ignore rules.

- [X] T001 Create the input-logging module skeleton (deliberately NOT named `logging`, to avoid shadowing the stdlib) in `src/ome_zarr_masker/input_log.py`
- [X] T002 [P] Add `ome_zarr_masker_logs/` to `.gitignore`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The run identifier, log configuration, and per-invocation log lifecycle that every user
story builds on.

**CRITICAL**: Tests (T003-T004) are written before their implementations (T005-T007) and must fail
first.

- [X] T003 [P] Unit test: run identifier is unique and time-sortable (`<UTC-timestamp>-<short-uuid>`) in `tests/unit/test_run_id.py`
- [X] T004 [P] Unit test: log lifecycle writes a per-invocation file with header + outcome, is best-effort on an unwritable directory (warns to stderr, raises nothing), and writes nothing to stdout, in `tests/unit/test_input_log.py`
- [X] T005 [P] Implement run identifier generation in `src/ome_zarr_masker/input_log.py`
- [X] T006 [P] Implement `LogConfig` (default `./ome_zarr_masker_logs`, verbosity level, enabled flag) in `src/ome_zarr_masker/config.py`
- [X] T007 Implement the per-invocation log lifecycle context manager (create `<log_dir>/<run_id>.log`, write header, append outcome on exit, best-effort wrapping, stderr-only warnings, never stdout) in `src/ome_zarr_masker/input_log.py` (depends on T005, T006)

**Checkpoint**: Logging mechanism works in isolation with the stub backend.

---

## Phase 3: User Story 1 - Log CLI invocation inputs (Priority: P1) MVP

**Goal**: Every CLI invocation writes a plain-text log file capturing the command, options, and
resolved effective configuration — including runs that fail before producing output.

**Independent Test**: Run the CLI once successfully and once with an invalid argument; both produce
a log file capturing the command and config.

### Tests for User Story 1 (write FIRST, must fail)

- [X] T008 [US1] Integration test: a successful CLI `mask` run writes `<log-dir>/<run-id>.log` with the command and effective config (C-LOG-CLI-1) in `tests/integration/test_log_cli.py`
- [X] T009 [US1] Integration test: a CLI run that fails before output (e.g., bad level) still writes a log file (C-LOG-CLI-2, FR-002) in `tests/integration/test_log_cli_failure.py`
- [X] T010 [P] [US1] Integration test: each invocation writes a distinct, non-colliding log file (C-LOG-CLI-3), and the run id in the log equals the run id in the output run-record (C-LOG-CLI-7, FR-005) in `tests/integration/test_log_cli_runid.py`
- [X] T011 [P] [US1] Integration test: with logging active, the tool's stdout contains no log lines and any machine-readable stdout stays parseable; logging notices appear on stderr only (C-LOG-CLI-4, FR-008, SC-005) in `tests/integration/test_log_stdout_clean.py`

### Implementation for User Story 1

- [X] T012 [US1] Record the invocation block (command line, parsed arguments, resolved effective configuration) on entry, before validation, in `src/ome_zarr_masker/input_log.py`
- [X] T013 [US1] Wire the log lifecycle into the CLI entry so every invocation (including failures) is logged, in `src/ome_zarr_masker/cli.py`
- [X] T014 [US1] Embed the run identifier in feature 001's output run-record for log/output correlation (FR-005) in `src/ome_zarr_masker/io/writer.py`

**Checkpoint**: MVP - all CLI invocations, success or failure, are logged; stdout stays clean.

---

## Phase 4: User Story 2 - Log prompt inputs (Priority: P2)

**Goal**: The landmark prompts used for a run are recorded (coordinates, labels, optional box,
frame/axis, source), for both CLI prompt files and the programmatic API.

**Independent Test**: Run with a known prompt file and confirm the log lists the same prompts and
source; run via the API and confirm equivalent logging.

### Tests for User Story 2 (write FIRST)

- [X] T015 [US2] Integration test: CLI prompts are recorded (coordinates, labels, optional box, frame/axis) with the prompt-file source, in `tests/integration/test_log_prompts_cli.py`
- [X] T016 [US2] Integration test: API-supplied prompts are logged equivalently with `prompt_source="api"` (C-LOG-API-1) and the run id is exposed on the result (C-LOG-API-3) in `tests/integration/test_log_api.py`
- [X] T017 [P] [US2] Unit test: a large prompt set is captured in full with the count in the header (FR-010, C-LOG-API-4) in `tests/unit/test_input_log_prompts.py`

### Implementation for User Story 2

- [X] T018 [US2] Record the prompts block from the `PromptSet` (full content + count + source) in `src/ome_zarr_masker/input_log.py`
- [X] T019 [US2] Wire the log lifecycle into the API `predict` path (`prompt_source="api"`; expose the run id on the result) in `src/ome_zarr_masker/api.py`

**Checkpoint**: Prompts recoverable from the log for both CLI and API runs.

---

## Phase 5: User Story 3 - Control log destination and verbosity (Priority: P3)

**Goal**: User controls where logs go and how verbose they are, without interfering with
machine-readable output.

**Independent Test**: Default run logs to the default location; an overridden destination and quieter
verbosity are honored.

### Tests for User Story 3 (write FIRST)

- [X] T020 [US3] Integration test: `--log-dir` and `--log-level` override the defaults (C-LOG-CLI-6, FR-007) in `tests/integration/test_log_options.py`
- [X] T021 [US3] Integration test: an unwritable `--log-dir` leaves the masking run successful with a single stderr warning (C-LOG-CLI-5, FR-009) in `tests/integration/test_log_besteffort.py`

### Implementation for User Story 3

- [X] T022 [US3] Add `--log-dir` and `--log-level` CLI options (standard logging level names; default `INFO`) and `log_dir`/`log_level` API parameters in `src/ome_zarr_masker/cli.py` and `src/ome_zarr_masker/api.py`
- [X] T023 [US3] Ensure lower verbosity never drops the core invocation/prompt record needed for reproducibility, in `src/ome_zarr_masker/input_log.py`

**Checkpoint**: Destination and verbosity configurable; logging never corrupts stdout.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T024 [P] Performance test: logging adds < 50 ms per invocation and does not scale with volume size, in `tests/performance/test_log_overhead.py`
- [X] T025 [P] Update `README.md`/docs with logging behavior and the `--log-dir`/`--log-level` options
- [X] T026 [P] Type-hint/docstring pass and `ruff`/`ruff format` clean across `src/ome_zarr_masker/input_log.py` and touched files
- [X] T027 Execute the `quickstart.md` scenarios end-to-end as a final validation pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories. Tests T003-T004 precede impl T005-T007.
- **US1 (Phase 3)**: Depends on Foundational. The MVP.
- **US2 (Phase 4)**: Depends on Foundational + US1 lifecycle wiring.
- **US3 (Phase 5)**: Depends on Foundational; independent of US2 (both build on the US1 wiring).
- **Polish (Phase 6)**: Depends on the targeted stories.
- **Cross-feature**: Builds on feature 001's CLI, API, `RunConfig`, `PromptSet`, and output run-record; implement after/alongside those exist (T013/T014/T019/T022 edit feature-001 files).

### Within Each User Story

- Tests written and failing before implementation (Constitution Principle II).
- Inputs recorded on entry before validation so failed runs are logged; outcome appended on exit.

## Parallel Opportunities

- Setup: T002 in parallel with T001.
- Foundational: tests T003-T004 in parallel; impl T005 and T006 in parallel (distinct files), then T007.
- US1: T010-T011 [P] alongside T008/T009 authoring; impl T012-T014 are mostly sequential (shared module/CLI).
- US2: T017 [P] alongside T015/T016.
- US3 can be developed in parallel with US2 once Foundational + US1 are done.
- Polish: T024, T025, T026 in parallel.

### Parallel Example: Foundational

```bash
# Write foundational tests together (write-first):
Task: "Unit test for run identifier in tests/unit/test_run_id.py"
Task: "Unit test for log lifecycle in tests/unit/test_input_log.py"
# Then implement in parallel where files differ:
Task: "Implement run id in src/ome_zarr_masker/input_log.py"
Task: "Implement LogConfig in src/ome_zarr_masker/config.py"
```

## Implementation Strategy

### MVP First (User Story 1 only)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational).
2. Complete Phase 3 (US1): every CLI invocation, success or failure, is logged and stdout stays clean.
3. STOP and VALIDATE: run the US1 tests and quickstart Scenarios 1-3.

### Incremental Delivery

1. Setup + Foundational -> logging mechanism works.
2. US1 -> all CLI invocations logged (MVP).
3. US2 -> prompts logged for CLI and API.
4. US3 -> destination/verbosity control.
5. Polish -> overhead benchmark, docs, final validation.

## Notes

- [P] = different files, no dependency on incomplete tasks.
- Every behavioral task is preceded by a failing test (Principle II); commit after each task or
  logical group, keeping each commit green (Principle III).
- Logging is best-effort and stdout-clean; tests assert both (FR-008, FR-009).
