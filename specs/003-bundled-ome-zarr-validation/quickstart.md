# Quickstart & Validation Guide: Bundled OME-Zarr Validation Dependency

**Feature**: 003-bundled-ome-zarr-validation | **Date**: 2026-06-23

Runnable scenarios proving input validation works from a plain install with no validator command on
`PATH`. References the [contract](./contracts/validation.md) and [data model](./data-model.md)
rather than duplicating them.

## Prerequisites

- ome-zarr-masker installed (a plain `pip install -e .` is enough — `ome-zarr-models>=1.6` and
  `zarr>=3` come in as declared dependencies). No backend extra and no validator command on `PATH`
  are required for validation.
- The synthetic OME-Zarr v0.5 fixture from `tests/conftest.py::write_ome_zarr` (reused by the
  validation unit tests).

## Scenario 1 — Valid store passes with no validator on PATH (US1, US3)

```bash
# Ensure no ome-zarr-models command is reachable, then validate in-process:
env PATH=/usr/bin:/bin .venv/bin/python - <<'PY'
import shutil
assert shutil.which("ome-zarr-models") is None   # no validator command on PATH
from ome_zarr_masker.io.validate import validate_ome_zarr
validate_ome_zarr("path/to/valid.ome.zarr")       # returns None, no raise
print("valid")
PY
```

Expected: prints `valid`; validation succeeds purely from the installed package. (C-VAL-1, SC-003)

## Scenario 2 — No subprocess is spawned (US1)

Run the unit test that patches `subprocess.run`/`Popen` and asserts validation never calls them.

```bash
.venv/bin/pytest tests/unit/test_validate.py -q
```

Expected: the in-process validation test passes and confirms no child process is spawned. (C-VAL-2)

## Scenario 3 — Invalid and missing stores are still rejected (US1)

```bash
.venv/bin/python - <<'PY'
from ome_zarr_masker.io.validate import validate_ome_zarr, ValidationError
for bad in ["does/not/exist.ome.zarr", "path/to/not_a_zarr_dir"]:
    try:
        validate_ome_zarr(bad)
        print("UNEXPECTED PASS", bad)
    except ValidationError as e:
        print("rejected:", e)
PY
```

Expected: both are rejected with `ValidationError`; the message says the store does not exist or is
not a valid OME-Zarr v0.5 store. (C-VAL-3, C-VAL-4, SC-002)

## Scenario 4 — End-to-end CLI run validates from a plain install (US1)

```bash
ome-zarr-masker mask valid.ome.zarr out.ome.zarr --prompts prompts.json --backend stub --level 0
echo "exit: $?"     # 0 — validation passed without any PATH setup
```

Expected: the run proceeds past validation with zero manual environment setup beyond installing the
package. (SC-001)

## Scenario 5 — Documentation has no on-PATH prerequisite (US2)

```bash
grep -rni "validate.*on .*PATH\|CLI on .PATH" README.md specs/003-bundled-ome-zarr-validation/
```

Expected: no remaining instruction to put or verify a validator command on `PATH`; docs state
validation is provided by the installed package. (SC-004, FR-006)

## Performance check (Principle IV)

A test times `validate_ome_zarr` on the synthetic valid store and asserts it completes under the
budget (< 500 ms) while spawning no sub-process. (C-VAL-7, SC-005)
