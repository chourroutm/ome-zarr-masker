# Feature Specification: Logging of Prompt and CLI Inputs

**Feature Branch**: `002-input-logging`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "log prompt and cli inputs"

## Overview

ome-zarr-masker records, for every masking invocation, the inputs that drove it: the
command-line invocation (command, arguments, options, and the resolved effective configuration
after defaults are applied) and the landmark prompts used (points with labels, optional box, per
frame/axis), regardless of whether the prompts arrived from a CLI prompt file or the programmatic
API. These are written to a per-invocation plain-text log file so a user can audit, debug, and
reconstruct what was asked of the tool.

This complements the reproducibility run-record that is written alongside a successful output
(feature 001, FR-014): unlike that sidecar, the input log is written even when a run fails or is
rejected before any output exists, giving a durable trail for troubleshooting bad inputs.

## Clarifications

### Session 2026-06-14

- Q: What format should the input log use? → A: Plain text (human-readable; not a structured machine format).
- Q: How should log entries be organized on disk? → A: One plain-text log file per invocation, named by run identifier/timestamp.
- Q: Where should the default log location be (overridable)? → A: A logs subdirectory of the current working directory (e.g. `ome_zarr_masker_logs/`), gitignored; overridable.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Log CLI invocation inputs (Priority: P1)

A user runs the tool from the command line and later needs to know exactly what command and
options produced a given result (or failure). Each invocation appends a timestamped entry capturing
the command line, the parsed arguments/options, and the resolved effective configuration.

**Why this priority**: This is the core value: a durable record of how the tool was invoked, usable
even when a run errors out before producing output.

**Independent Test**: Run the CLI once successfully and once with an invalid argument; confirm both
produce a log entry capturing the command and options, including the failed run.

**Acceptance Scenarios**:

1. **Given** any CLI invocation, **When** it runs, **Then** a timestamped log entry records the
   command, the provided arguments/options, and the resolved effective configuration.
2. **Given** an invocation that fails validation or errors before producing output, **When** it
   exits, **Then** the log entry for that invocation is still written.
3. **Given** multiple sequential invocations, **When** they run, **Then** each appends a distinct
   entry without overwriting earlier ones.

---

### User Story 2 - Log prompt inputs (Priority: P2)

A user needs to recover the exact landmark prompts that were used for a run. The logged entry
includes the prompts (point coordinates, labels, optional box, with their frame/axis and object
association) and the source they came from (prompt file path or programmatic API).

**Why this priority**: Prompts are the other half of "what was asked"; together with the CLI inputs
they make a run reconstructable. It builds on the same logging mechanism as US1.

**Independent Test**: Run with a known prompt file and confirm the log entry lists the same prompts
(coordinates, labels, box) and names the prompt source; run via the API and confirm equivalent
prompt logging.

**Acceptance Scenarios**:

1. **Given** a run with landmark prompts, **When** it runs, **Then** the log entry records the
   prompts (coordinates, labels, optional box, frame/axis) and the prompt source.
2. **Given** prompts supplied programmatically through the API, **When** a run executes, **Then**
   the prompts are logged equivalently to the CLI prompt-file case.
3. **Given** a large set of prompts, **When** logged, **Then** the entry remains readable (the count
   is recorded and the content is captured or referenced without truncating to the point of losing
   reproducibility).

---

### User Story 3 - Control log destination and verbosity (Priority: P3)

A user wants to choose where logs are written and how much is logged, so logging fits their
environment (interactive console, file, or both) without interfering with machine-readable output.

**Why this priority**: Sensible defaults make US1/US2 useful out of the box; configurability is a
refinement for different environments and pipelines.

**Independent Test**: Run with default settings (entry appears in the default log location), then
run with an overridden destination and a quieter verbosity, and confirm the log honors both.

**Acceptance Scenarios**:

1. **Given** default settings, **When** a run executes, **Then** the input log is written to the
   documented default location.
2. **Given** a user-specified log destination and/or verbosity, **When** a run executes, **Then**
   the log honors the chosen destination and level.
3. **Given** the tool also emits machine-readable output, **When** logging is active, **Then** log
   output does not corrupt or intermix with that machine-readable output stream.

---

### Edge Cases

- What happens when the log destination is not writable (permissions, full disk)? The tool surfaces
  a clear warning and continues the run (logging failure must not silently abort masking), or fails
  clearly if logging is explicitly required.
- How are concurrent invocations handled? Each invocation writes its own uniquely-named log file
  (run id/timestamp), so concurrent runs do not interleave or corrupt each other; name collisions
  must be avoided (e.g., include a unique run identifier).
- How is a very large prompt set recorded without making the log unusable?
- What is logged when an invocation is interrupted mid-run (the entry must still reflect the inputs
  that were provided)?
- Do logged inputs contain anything sensitive? Inputs are file paths, coordinates, and option
  values; the log records them as-is, and the documented behavior states no separate secret handling
  is expected.
- How are non-ASCII characters in file paths or option values recorded?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST write a timestamped, plain-text log file for every CLI invocation,
  capturing the command, the provided arguments/options, and the resolved effective configuration
  (after defaults).
- **FR-002**: System MUST write the input log entry even when the invocation fails or is rejected
  before producing output.
- **FR-003**: System MUST log the landmark prompts used for a run (point coordinates, labels,
  optional box, with frame/axis and object association) and the source of those prompts (prompt-file
  path or programmatic API).
- **FR-004**: System MUST log prompts supplied through the programmatic API equivalently to prompts
  supplied via a CLI prompt file.
- **FR-005**: System MUST associate each log entry with a run identifier and timestamp so entries
  can be correlated to a specific invocation (and to its output run-record when one exists).
- **FR-006**: System MUST write one log file per invocation, named by run identifier/timestamp, so
  invocations stay distinct and no run overwrites another run's log file.
- **FR-007**: System MUST write logs by default to a logs subdirectory of the current working
  directory (e.g. `ome_zarr_masker_logs/`) and MUST allow the user to override the destination
  directory and the verbosity level.
- **FR-008**: System MUST keep log output separate from any machine-readable output stream so that
  logging never corrupts the tool's parseable output.
- **FR-009**: System MUST handle a failure to write the log gracefully: by default a logging failure
  produces a clear warning and does not abort the masking run.
- **FR-010**: System MUST record large prompt sets in a way that preserves reproducibility (record
  the count and capture the full prompt content in the plain-text log rather than truncating it
  away).

### Key Entities *(include if feature involves data)*

- **Input Log**: The collection of per-invocation plain-text log files in the log directory; the
  durable trail of what was asked of the tool.
- **Invocation Log File**: One plain-text file per invocation, named by run identifier/timestamp;
  contents include timestamp, run identifier, the command line, parsed arguments/options, resolved
  effective configuration, the prompts used, and run outcome (succeeded/failed) when known.
- **Prompt Log Detail**: The prompts recorded for an invocation (coordinates, labels, optional box,
  frame/axis, object association) and their source (file path or API).
- **Run Identifier**: A value correlating an invocation's log entry with its output run-record
  (feature 001, FR-014) when an output is produced.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of CLI invocations, including failed ones, produce a plain-text log file
  capturing the command and effective configuration.
- **SC-002**: From the log alone, a user can identify the command, options, and prompts that drove
  any given run, with no access to the original prompt file required.
- **SC-003**: Prompts supplied via the API and via a CLI prompt file are both recoverable from the
  log with equivalent detail.
- **SC-004**: Logging adds no user-perceptible overhead to a run (negligible relative to masking
  time).
- **SC-005**: When the tool emits machine-readable output, that output remains valid and parseable
  with logging active.
- **SC-006**: A logging failure (e.g., unwritable destination) never aborts an otherwise-valid
  masking run under default settings; the user is warned.

## Assumptions

- This feature concerns logging the *inputs* (CLI invocation + prompts). It complements, and does
  not replace, the output run-record written alongside successful masks (feature 001, FR-014); the
  run identifier ties the two together.
- By default each invocation writes its own plain-text log file into a logs subdirectory of the
  current working directory (e.g. `ome_zarr_masker_logs/`), overridable via option/environment. Like
  feature 001's model directory, this default location should be excluded from version control.
- Logs are plain text and human-readable, not a structured machine format; verbosity is adjustable.
  The exact filename pattern and verbosity levels are finalized in planning.
- Logged inputs (paths, coordinates, option values) are not treated as secrets; no redaction is
  performed by default.
- Logging is best-effort by default (a logging failure warns but does not abort the run); a stricter
  "fail if logging fails" behavior, if offered, is finalized in planning.
- Single-user, local execution as in feature 001; high-concurrency log contention is not a primary
  scenario but entries should not corrupt each other.

## Dependencies

- The masking workflows and inputs defined in feature 001 (CLI one-shot, programmatic API, prompt
  model) are the source of the inputs being logged.
- The reproducibility run-record (feature 001, FR-014) shares the run identifier used to correlate
  logs with outputs.
