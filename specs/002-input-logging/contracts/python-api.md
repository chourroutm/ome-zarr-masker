# Contract: Python API Logging Integration

**Feature**: 002-input-logging | **Date**: 2026-06-14

Logging is integrated into feature 001's `OrganMaskPredictor` run lifecycle so that prompts supplied
programmatically are logged equivalently to the CLI prompt-file case (FR-004).

## Configuration

`OrganMaskPredictor(..., log_dir=None, log_level=None)`
- `log_dir`: override the default `./ome_zarr_masker_logs` (FR-007); `None` => default/env.
- `log_level`: verbosity (FR-007); `None` => full-detail default.

## Behavior

- A `predict(...)` run opens a per-invocation plain-text log file before processing, recording
  `command="api"`, the effective configuration, and the prompts added via `add_points`/`add_box`
  with their coordinates/labels/box/frame/axis and `prompt_source="api"` (FR-003, FR-004).
- A failed `predict(...)` (e.g., invalid prompts) still writes the log file (FR-002).
- The `MaskResult`/run exposes the run identifier so callers can correlate the log file with the
  saved output run-record (FR-005).
- Logging is best-effort: a logging failure raises no error to the caller and does not prevent
  `predict` from running (FR-009); nothing is written to stdout (FR-008).

## Behavioral contract (testable)

- C-LOG-API-1: An API `predict` run writes a log file recording `prompt_source="api"` and the full
  prompts, equivalent in detail to the CLI case. *(US2, FR-004)*
- C-LOG-API-2: A failed API `predict` still writes a log file. *(FR-002)*
- C-LOG-API-3: The run id exposed by the API equals the run id in the log file and in the saved
  output run-record. *(FR-005)*
- C-LOG-API-4: A large programmatic prompt set is captured in full in the log. *(FR-010)*
- C-LOG-API-5: API and CLI logs record equivalent prompt detail for the same prompts. *(SC-003)*
