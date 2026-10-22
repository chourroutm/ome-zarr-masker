# Quickstart & Validation Guide: Logging of Prompt and CLI Inputs

**Feature**: 002-input-logging | **Date**: 2026-06-14

Runnable scenarios proving input logging works. References the contracts and data model rather than
duplicating them (see [contracts/](./contracts/), [data-model.md](./data-model.md)).

## Prerequisites

- The ome-zarr-masker package installed (feature 001), with a backend extra for real runs; the
  stub backend suffices for logging tests.
- A synthetic OME-Zarr v0.5 input and a prompt file (reuse feature 001's test fixtures).
- Logging needs no extra dependencies (standard library only). Default log directory is
  `./ome_zarr_masker_logs/`.

## Scenario 1 — CLI run is logged (US1)

```bash
ome-zarr-masker mask input.ome.zarr output.ome.zarr --prompts prompts.json --axes z
ls ome_zarr_masker_logs/                      # a <run-id>.log file exists
grep -i "command\|level\|axes" ome_zarr_masker_logs/*.log
```

Expected: a plain-text log file recording the command line, the resolved effective configuration,
and the prompts. (C-LOG-CLI-1)

## Scenario 2 — Failed run is still logged (US1)

```bash
ome-zarr-masker mask input.ome.zarr output.ome.zarr --prompts prompts.json --level 999  # bad level
echo "exit: $?"                             # non-zero
ls ome_zarr_masker_logs/                       # a log file for this failed run still exists
```

Expected: the run exits non-zero with no output mask, yet a log file capturing the attempted command
and config is present. (C-LOG-CLI-2, FR-002)

## Scenario 3 — stdout stays clean (US1)

```bash
ome-zarr-masker mask input.ome.zarr output.ome.zarr --prompts prompts.json --axes z 1>stdout.txt 2>stderr.txt
grep -ci "log" stdout.txt                    # expect 0 logging lines on stdout
```

Expected: no logging output on stdout; any logging notices are on stderr only. (C-LOG-CLI-4, FR-008)

## Scenario 4 — API prompts are logged equivalently (US2)

```python
from ome_zarr_masker import OrganMaskPredictor

p = OrganMaskPredictor(backend="sam2")
p.set_volume("input.ome.zarr", level=3)
p.add_points(frame_index=120, point_coords=[[340, 512]], point_labels=[1])
result = p.predict(axes=["z"])
print(result.run_id)                         # matches the <run-id>.log filename
```

Expected: a log file records `prompt_source="api"` and the prompts in full, equivalent to the CLI
case; `result.run_id` matches the log filename and the saved output's run-record. (C-LOG-API-1,
C-LOG-API-3)

## Scenario 5 — Override destination and verbosity (US3)

```bash
ome-zarr-masker mask input.ome.zarr output.ome.zarr --prompts prompts.json \
  --log-dir /tmp/oml-logs --log-level WARNING
ls /tmp/oml-logs/                            # log written to the overridden directory
```

Expected: the log is written to the overridden directory at the chosen verbosity, while still
recording the core invocation/prompt detail. (C-LOG-CLI-6, FR-007)

## Scenario 6 — Best-effort on unwritable destination (FR-009)

```bash
ome-zarr-masker mask input.ome.zarr output.ome.zarr --prompts prompts.json \
  --log-dir /proc/forbidden 2>stderr.txt
echo "exit: $?"                              # masking still succeeds (0)
grep -i "warn" stderr.txt                    # a logging warning is present
```

Expected: the masking run completes; a single stderr warning notes that logging could not be
written. (C-LOG-CLI-5)

## Scenario 7 — Large prompt set captured in full (FR-010)

Run with a prompt file containing many points and confirm the log records the count in the header
and lists every prompt without truncation. (C-LOG-API-4)

## Test Data

- Reuse feature 001's synthetic OME-Zarr fixture and stub backend; logging assertions read the
  written `<run-id>.log` files.

## Performance check (Principle IV)

- A timing test asserts logging adds under 50 ms per invocation and does not scale with volume size.
