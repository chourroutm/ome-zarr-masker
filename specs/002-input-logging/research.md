# Phase 0 Research: Logging of Prompt and CLI Inputs

**Feature**: 002-input-logging | **Date**: 2026-06-14

Decisions resolving the planning unknowns. The clarification session already fixed format (plain
text), organization (one file per invocation), and default location (working-directory subdir); the
items below cover the remaining mechanics.

## R1. Logging mechanism

**Decision**: Use the Python standard-library `logging` module with a per-invocation `FileHandler`
and a plain-text formatter. No third-party logging dependency. The feature module is named
`input_log.py` (not `logging.py`) to avoid shadowing the stdlib package.

**Rationale**: Keeps the dependency surface minimal (a project constraint), gives verbosity levels
for free (FR-007), and writes plain text (the clarified format). A FileHandler per invocation
naturally yields one file per run.

**Alternatives considered**: A third-party logging library (structlog/loguru) — unnecessary
dependency for plain-text output; rejected. Writing the file by hand with `open()` — viable but
reimplements level handling; the stdlib handler is simpler and standard.

## R2. Run identifier and correlation with feature 001

**Decision**: Generate a run identifier at invocation start as `<UTC-timestamp>-<short-uuid>` (e.g.
`20260614T101530Z-a1b2c3`). Use it as the log filename stem and pass the same value into feature
001's output run-record (FR-014) so a log file and its produced mask correlate (FR-005).

**Rationale**: A timestamped, collision-resistant id gives human-sortable filenames and a stable key
linking the input log to the output sidecar. Including a short uuid avoids collisions for concurrent
or same-second runs (the concurrency edge case).

**Alternatives considered**: Pure timestamp (collision risk under concurrency); pure uuid (not
human-sortable). Rejected in favor of the combination.

## R3. Where logging attaches (lifecycle)

**Decision**: A context manager in `input_log.py` is entered at the very start of the CLI command
and the API run. On entry it creates the run id, opens the log file, and immediately records the
command/arguments/effective config and prompts. The outcome (succeeded/failed + error summary) is
written in the `finally`/exit path. CLI and API both use this one lifecycle.

**Rationale**: Recording inputs on entry guarantees a log even when later validation/processing
fails before any output (FR-002). A single shared lifecycle keeps CLI and API logging equivalent
(FR-004) without duplicated code.

**Alternatives considered**: Logging only after a successful run — fails FR-002; rejected. Separate
CLI and API logging paths — duplication and drift risk; rejected.

## R4. Plain-text record content and large prompts

**Decision**: Each log file is human-readable plain text with labeled sections: a header (timestamp,
run id, outcome placeholder), an invocation block (command line, parsed args, resolved effective
config), and a prompts block listing every prompt (coordinates, label, optional box, frame/axis,
object, and source). The full prompt set is written (no truncation); the count is recorded in the
header (FR-010).

**Rationale**: Labeled plain text is the clarified format and is readable without tooling while
still being greppable. Writing prompts in full preserves reproducibility (SC-002/SC-003) even for
large sets, at negligible IO cost.

**Alternatives considered**: Truncating large prompt sets — breaks reproducibility; rejected.
Structured JSON — not the clarified format; rejected.

## R5. Stream separation and best-effort behavior

**Decision**: The input log is written only to its file; any user-facing logging notices go to
stderr. Nothing logging-related is written to stdout, so the tool's machine-readable output stays
clean (FR-008). All log writes are wrapped so that a logging failure (e.g., unwritable directory,
full disk) emits a single stderr warning and the masking run proceeds (FR-009). A future strict mode
(fail-if-logging-fails) is out of scope unless requested.

**Rationale**: Directly encodes FR-008 and FR-009. Best-effort default ensures logging never costs a
user their masking result.

**Alternatives considered**: Aborting on logging failure by default — hostile to the primary task;
rejected as the default.

## R6. Default location and version control

**Decision**: Default log directory is `./ome_zarr_masker_logs/` (working-directory subdir),
overridable via a `--log-dir` option and an environment variable. The default directory is added to
the project `.gitignore`.

**Rationale**: Matches the clarified location and feature 001's model-directory-in-cwd convention;
gitignoring prevents committing logs (Principle III: no generated artifacts committed).

**Alternatives considered**: Covered in the clarification session; not re-litigated.

## R7. Verbosity

**Decision**: A `--log-level` option (and matching API parameter) maps to stdlib logging levels;
default records the full input detail (info-level). Lower verbosity reduces ancillary messages but
never drops the core invocation/prompt record needed for reproducibility.

**Rationale**: Gives FR-007 control without risking the auditability guarantee (SC-002).

## Resolved unknowns

All Technical Context items are resolved; no `NEEDS CLARIFICATION` markers remain. The exact log
filename pattern and the names of verbosity levels are minor presentation details fixed during
implementation within the decisions above.
