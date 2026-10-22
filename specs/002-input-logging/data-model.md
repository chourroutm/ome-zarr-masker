# Phase 1 Data Model: Logging of Prompt and CLI Inputs

**Feature**: 002-input-logging | **Date**: 2026-06-14

In-memory/on-disk domain objects (no database). Field names are indicative of the Python API. This
feature reuses feature 001's `RunConfig` and `PromptSet`.

## RunIdentifier

A unique, human-sortable identifier for one invocation; the log filename stem and the correlation
key with feature 001's output run-record.

| Field | Type | Notes |
|-------|------|-------|
| `value` | str | `<UTC-timestamp>-<short-uuid>`, e.g. `20260614T101530Z-a1b2c3` (research R2) |

Validation rules:
- MUST be unique per invocation (timestamp + short uuid) to avoid filename collisions (FR-006).
- MUST be the same value embedded in the output run-record when a mask is produced (FR-005).

## LogConfig

Logging configuration for a run (lives with feature 001's `RunConfig`).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `log_dir` | path | `./ome_zarr_masker_logs` | Override via `--log-dir`/env (FR-007) |
| `level` | stdlib level name | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`; controls ancillary messages only (FR-007, R7) |
| `enabled` | bool | `true` | Logging on by default |

Validation rules:
- If `log_dir` is unwritable, logging degrades to a stderr warning; the run continues (FR-009).

## InvocationLogFile

One plain-text log file per invocation (research R4).

| Section / Field | Type | Notes |
|-----------------|------|-------|
| `path` | path | `<log_dir>/<run_id>.log` |
| `timestamp` | datetime (UTC) | Invocation start time |
| `run_id` | RunIdentifier | Header; correlates to the output run-record (FR-005) |
| `command` | str | Full CLI command line (or `api` for programmatic runs) |
| `arguments` | mapping | Parsed CLI arguments/options |
| `effective_config` | mapping | Resolved `RunConfig` after defaults applied (FR-001) |
| `prompts` | list | Every prompt: coordinates, label, optional box, frame/axis, object (FR-003, FR-010) |
| `prompt_source` | str | Prompt-file path or `api` (FR-003, FR-004) |
| `prompt_count` | int | Recorded in the header for large sets (FR-010) |
| `outcome` | enum {`succeeded`,`failed`} + summary | Written at run end; failures still produce the file (FR-002) |

Validation rules:
- The file MUST be written even when the run fails before producing output (FR-002).
- Inputs are recorded on entry; outcome is appended on exit (research R3).
- Content is plain text; the full prompt set is captured, not truncated (FR-010).
- Written only to the file; nothing to stdout (FR-008).

## Relationships

- One invocation produces exactly one `InvocationLogFile` identified by one `RunIdentifier`.
- `RunIdentifier` links an `InvocationLogFile` to feature 001's output run-record (FR-014) when a
  mask is produced; for failed runs the log file exists with no corresponding output.
- `LogConfig` parameterizes where/how the `InvocationLogFile` is written.
- `prompts`/`prompt_source` are derived from feature 001's `PromptSet` and its origin (CLI file or
  API).
