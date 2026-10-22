# Implementation Plan: Logging of Prompt and CLI Inputs

**Branch**: `002-input-logging` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-input-logging/spec.md`

## Summary

ome-zarr-masker writes a plain-text log file for every invocation, capturing the CLI command,
parsed arguments, the resolved effective configuration, and the landmark prompts used (from a CLI
prompt file or the programmatic API) — including for runs that fail before producing output. The
technical approach: a small input-logging module in the existing package, built on the Python
standard library only (no new dependencies). Each invocation generates a run identifier and opens
one plain-text log file named by that id/timestamp under a working-directory logs subdirectory
(default `ome_zarr_masker_logs/`, overridable, gitignored). Inputs are recorded immediately at the
start of a run so early failures are still captured; the outcome is appended at the end. Logging is
best-effort (a logging failure warns on stderr but never aborts a valid run) and is kept off the
machine-readable stdout stream. The same run identifier is embedded in feature 001's output
run-record so a log file and its mask output can be correlated.

## Technical Context

**Language/Version**: Python 3.11+ (same package as feature 001).

**Primary Dependencies**: Python standard library only — `logging` (file handler + plain-text
formatter), `pathlib`, `datetime`, `uuid`. No new third-party runtime dependencies; the core stays
minimal. Reuses feature 001's `RunConfig`, `PromptSet`, CLI, and API surfaces.

**Storage**: Plain-text log files on the local filesystem, one per invocation, named by run
identifier/timestamp, under a logs directory defaulting to `./ome_zarr_masker_logs/` (overridable via
option/environment).

**Testing**: `pytest`. Tests read back written log files and assert content; cover success, failure
before output, API-sourced prompts, large prompt sets, stdout separation, and best-effort behavior
when the log directory is unwritable.

**Target Platform**: Linux/macOS workstation (same as feature 001).

**Project Type**: Extension of the single Python package (an input-logging module wired into the CLI
and API entry points and the run lifecycle).

**Performance Goals** (Principle IV): Logging adds negligible overhead — under 50 ms per invocation
and well under 1% of a typical masking run; it performs a bounded amount of text IO independent of
volume size.

**Constraints**:
- Log output MUST NOT be written to stdout (kept to the log file; warnings to stderr) so
  machine-readable output stays clean (FR-008).
- Logging is best-effort by default: a logging failure warns but never aborts a valid run (FR-009).
- Inputs MUST be recorded before validation/processing so failed runs are still logged (FR-002).
- The run identifier MUST be the same value embedded in feature 001's output run-record (FR-005).

**Scale/Scope**: Single-user, one log file per invocation. Prompt sets from a handful to thousands
of points recorded in full (FR-010). Three prioritized user stories (CLI inputs, prompt inputs,
destination/verbosity control).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.0 (four core principles):

- **I. Code Quality Standards** — PASS (planned). `ruff` lint+format; typed module; one logging
  module reused by CLI and API (no duplicated logging logic). Module named to avoid shadowing the
  stdlib `logging` package.
- **II. Test Discipline (NON-NEGOTIABLE)** — PASS (planned). Tests written first for: log written on
  success, log written on failure-before-output, API-prompt logging, large-prompt capture, stdout
  separation, and best-effort behavior on an unwritable directory.
- **III. Disciplined Version Control** — PASS (planned). Atomic, green commits per task.
- **IV. Performance Requirements** — PASS (planned). Negligible-overhead target above, guarded by a
  timing assertion.

No violations. No new dependencies (standard library only), so nothing to record in Complexity
Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/002-input-logging/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── cli.md           # Logging-related CLI options
│   └── python-api.md    # Logging integration in the API
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
src/ome_zarr_masker/
├── input_log.py         # NEW: run id, log-file lifecycle, plain-text record of inputs + outcome
│                        #      (module deliberately NOT named `logging` to avoid shadowing stdlib)
├── config.py            # extended: LogConfig (log_dir default ./ome_zarr_masker_logs, verbosity)
├── cli.py               # wire global --log-dir/--log-level; open log at entry, record outcome
└── api.py               # wire logging into OrganMaskPredictor run lifecycle

tests/
├── unit/
│   └── test_input_log.py        # record/format, run id, best-effort failure, large prompts
└── integration/
    ├── test_log_cli.py          # CLI: success + failed run both produce a log file; stdout clean
    └── test_log_api.py          # API-sourced prompts logged equivalently
```

**Structure Decision**: A single `input_log.py` module owns run-identifier generation and the
per-invocation plain-text log file; both `cli.py` and `api.py` call it through one entry/exit
lifecycle (context manager) so CLI and API log equivalently (FR-004) with no duplicated logic
(FR-011 spirit). `LogConfig` lives with feature 001's `config.py`. The module is intentionally not
named `logging` to avoid shadowing the standard-library package it builds on.

## Dependencies / Sequencing

This feature builds on feature 001's entry points (CLI, API), `RunConfig`, and `PromptSet`, and
shares the run identifier with 001's output run-record (FR-014 <-> FR-005). It is implemented after
or alongside those 001 surfaces exist; the logging hooks attach at the same CLI/API entry points.

## Complexity Tracking

> No constitution violations and no new dependencies; nothing to justify.
