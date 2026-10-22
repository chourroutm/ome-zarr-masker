# Contract: CLI Logging Options

**Feature**: 002-input-logging | **Date**: 2026-06-14

Logging applies to all `ome-zarr-masker` subcommands (notably `mask` from feature 001). These are
global options; logging is on by default.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--log-dir PATH` | `./ome_zarr_masker_logs` | Directory for per-invocation log files (FR-007); also via env var |
| `--log-level LEVEL` | `INFO` | Standard logging level name (`DEBUG`, `INFO`, `WARNING`, `ERROR`); controls ancillary messages only and never drops the core invocation/prompt record (FR-007) |

(No `--no-log` in v1; logging is best-effort and always attempted. A strict/disable mode is out of
scope unless requested.)

## Behavior

- On every invocation, before validation, a plain-text log file `<log-dir>/<run-id>.log` is created
  capturing the command line, parsed options, and resolved effective configuration (FR-001).
- The prompts (from `--prompts`) are recorded with coordinates, labels, optional box, frame/axis,
  and source (FR-003).
- If the run fails before producing output, the log file is still written (FR-002).
- Log content goes only to the file; warnings (e.g., unwritable `--log-dir`) go to stderr; stdout is
  never used for logging (FR-008).
- If logging cannot be written, the masking run still proceeds and a single stderr warning is shown
  (FR-009).
- The run identifier in the log matches the one embedded in the produced mask's run-record (FR-005).

## Behavioral contract (testable)

- C-LOG-CLI-1: A successful `mask` run writes `<log-dir>/<run-id>.log` containing the command,
  effective config, and prompts. *(US1, US2)*
- C-LOG-CLI-2: A run that fails validation (e.g., bad input/level/prompts) still writes a log file
  capturing the attempted command and config. *(US1, FR-002)*
- C-LOG-CLI-3: Each invocation produces a distinct log file; two runs never collide or overwrite.
  *(FR-006)*
- C-LOG-CLI-4: With machine-readable stdout active, stdout contains no log lines; logging warnings
  appear on stderr only. *(FR-008)*
- C-LOG-CLI-5: With an unwritable `--log-dir`, the masking run still completes and a stderr warning
  is emitted. *(FR-009)*
- C-LOG-CLI-6: `--log-dir` and `--log-level` override the defaults. *(US3, FR-007)*
- C-LOG-CLI-7: The run id in the log file equals the run id in the output run-record. *(FR-005)*
