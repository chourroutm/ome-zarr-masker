# Implementation Plan: Bundled OME-Zarr Validation Dependency

**Branch**: `003-bundled-ome-zarr-validation` | **Date**: 2026-06-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-bundled-ome-zarr-validation/spec.md`

## Summary

Input validation currently shells out to the `ome-zarr-models validate` console script via
`subprocess`, which requires that script to be discoverable on `PATH` (or next to the interpreter).
This feature removes that prerequisite by validating **in-process** using the already-declared
`ome-zarr-models` package: call `ome_zarr_models.open_ome_zarr(store, version="0.5")` while treating
`ome_zarr_models.exceptions.ValidationWarning` as an error, exactly mirroring the package's own
`validate` CLI semantics. Validation then succeeds or fails based solely on the installed dependency,
never on `PATH`. Documentation is updated to drop the "validator CLI on PATH" prerequisite.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `ome-zarr-models>=1.6` (in-process `open_ome_zarr` + `exceptions.ValidationWarning`),
`zarr>=3`. Both are already declared runtime dependencies; no new dependency is added.

**Storage**: OME-Zarr v0.5 stores on the local filesystem (read-only during validation).

**Testing**: pytest. Existing `tests/unit/test_validate.py` is extended; the synthetic OME-Zarr
fixture (`tests/conftest.py::write_ome_zarr`) provides valid/invalid stores. No GPU/torch needed.

**Target Platform**: Linux/macOS CLI and Python library.

**Project Type**: Single project (library + CLI), existing layout under `src/ome_zarr_masker/`.

**Performance Goals**: Per-run input-validation time MUST NOT increase versus the subprocess approach
(SC-005). In-process validation removes a Python interpreter sub-process spawn, so it is expected to
be faster; a benchmark asserts validation of the synthetic valid store completes well under the
prior cost (budget: < 500 ms, and no subprocess spawned).

**Constraints**: No `PATH` dependency may remain (FR-001/FR-002). Validation outcomes must not
regress (FR-003/FR-004, SC-002): valid stores still pass, invalid/missing still raise
`ValidationError` with an actionable message. The public `validate_ome_zarr(path)` signature and the
`ValidationError` type are unchanged so callers (reader, pipeline, CLI, API) are unaffected.

**Scale/Scope**: One module rewritten (`io/validate.py`), its unit tests extended, one dependency
floor confirmed in `pyproject.toml`, and docs (README + this feature's data-model/quickstart, and
the feature-001 contract/quickstart references) updated. No public API surface change.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Code Quality**: Net simplification — removes `subprocess`, `shutil.which`, and interpreter-
  adjacent path probing in favor of a single in-process call. Lint/format clean. PASS.
- **II. Test Discipline (NON-NEGOTIABLE)**: A failing test is added first proving validation works
  with no validator on `PATH` (the on-`PATH` prerequisite is eliminated) plus a test asserting no
  subprocess is spawned; existing valid/invalid/missing tests must stay green. PASS.
- **III. Disciplined Version Control**: Atomic commits — (1) behavioral change (validate.py + tests),
  (2) docs, (3) any dependency-floor adjustment if needed — kept separate, each green. PASS.
- **IV. Performance Requirements**: Explicit budget declared above (no regression vs subprocess;
  no sub-process spawn) and validated by a benchmark/assertion. PASS.

No violations. Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/003-bundled-ome-zarr-validation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── validation.md
├── checklists/
│   └── requirements.md  # (from /speckit-specify)
├── spec.md
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
src/ome_zarr_masker/
└── io/
    └── validate.py          # CHANGED: in-process open_ome_zarr(..., version="0.5") gate

tests/
└── unit/
    └── test_validate.py     # EXTENDED: no-PATH validation, no-subprocess, missing-dep message

pyproject.toml               # CONFIRM/RAISE ome-zarr-models floor (FR-007)
README.md                    # CHANGED: drop "validate CLI on PATH" prerequisite (FR-006)
specs/001-ome-zarr-sam-masking/{quickstart.md,data-model.md,contracts/python-api.md,research.md}
                             # CHANGED: align stale "validate CLI on PATH" references (FR-006)
```

**Structure Decision**: Existing single-project layout is retained. The change is confined to one IO
module and its tests; the validation contract (`validate_ome_zarr(path) -> None`, raising
`ValidationError`) is preserved so no downstream module changes.

## Complexity Tracking

No constitution violations; table not required.
