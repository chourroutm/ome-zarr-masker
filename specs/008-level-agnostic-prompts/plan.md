# Implementation Plan: Level-Agnostic Prompt Coordinates

**Branch**: `008-level-agnostic-prompts` | **Date**: 2026-10-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-level-agnostic-prompts/spec.md`

## Summary

Prompt coordinates (`point_coords`, `box`, `frame_index`) are currently raw pixels tied to whichever
pyramid level was on screen when the prompt was authored; reusing a saved prompt set at a different
level silently shifts every point and produces a wrong mask with no error (the bug motivating this
feature). This feature adds one `level` field to `PromptSet` (authoring level, a traceability trace --
FR-002/FR-003) and one conversion step in the pipeline: before validating prompts against the run
level's shape, convert every coordinate from the authoring level's pixel grid to the run level's pixel
grid by physical position (each level's scale and translation, nearest pixel centre, ties to the
lower pixel; reworked 2026-10-16 from an original shape-ratio conversion, see research R8) -- no new
coordinate system, no new dependency. The on-disk prompt-file JSON gains a required top-level `"level"` key; files
written in the old, level-less format are rejected with a clear error (FR-007) rather than
silently reinterpreted.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged).

**Primary Dependencies**: None added. Conversion is plain `numpy`/stdlib arithmetic inside
`prompts/model.py`, driven by per-level shapes the reader (`io/reader.py::OmeZarrReader.level_shape`)
already exposes; it reads no new OME-Zarr metadata (no new reliance on `coordinateTransformations`).

**Storage**: OME-Zarr v0.5 stores on the local filesystem (unchanged, local-only -- remote sources
remain explicitly out of scope). The prompt-file JSON format (an `organ-masker-lite`-specific
contract, not an OME-Zarr artifact) gains one required field.

**Testing**: pytest. `tests/unit/test_prompts.py` gains conversion/round-trip/rejection cases;
`tests/integration/test_us3_levels.py` gains the cross-level-reuse acceptance scenario (spec User
Story 1); `tests/conftest.py::write_ome_zarr` gains an optional per-axis scale factor so an anisotropic
pyramid (sweep axis downsampled by a different factor than the in-plane axes) can be exercised (spec
Edge Cases, FR-004). Every existing test that hand-writes a prompt-file JSON (14 files; see Project
Structure) must add the new `"level"` key to keep passing under FR-007.

**Target Platform**: Linux/macOS CLI and Python library (unchanged).

**Project Type**: Single project (library + CLI), existing layout under `src/organ_masker_lite/`.

**Performance Goals**: Conversion is `O(n_prompts)` scalar arithmetic with no I/O -- adds no
measurable latency versus today (budget: < 4 ms for a prompt set of up to 500 prompts, a generous
ceiling for a thorough multi-frame annotation; asserted by a unit-level timing check. Per-prompt
reconstruction bypasses `Prompt`'s validating `__init__` via `Prompt.__new__`, since re-validating
already-known-valid data dominated cost at this scale (~15x the budget) before that change. No
dedicated performance-suite file is warranted, unlike feature 003-bundled-ome-zarr-validation's
subprocess-removal, since there is no I/O or subprocess cost here to
regress).

**Constraints**: No remote-source support is added (prior decision, reaffirmed in spec Assumptions).
The prompt-file JSON schema change is intentionally breaking (FR-007): no migration path for
pre-feature prompt files is in scope. Same-level reruns MUST stay byte-identical to current behavior
(FR-006, SC-002) -- the conversion step MUST be a true no-op (identity, not a 1.0-ratio recomputation)
when the authoring level equals the run level or is unset.

**Scale/Scope**: Confined to `src/organ_masker_lite/prompts/model.py` (new `PromptSet.level` field +
a shape-ratio conversion method), `src/organ_masker_lite/engine/pipeline.py` (one conversion call
ahead of the existing `prompts.validate(...)`, plus the existing-level-exists check), `src/
organ_masker_lite/api.py` (stamp the predictor's current level when `predict()` builds the
`PromptSet`, one line), `src/organ_masker_lite/input_log.py` (`record_prompts` logs the new level
trace), its unit/integration tests, and docs (`README.md`'s prompt-file example,
`specs/001-ome-zarr-sam-masking/data-model.md`'s `Prompt`/`PromptSet` entity tables, and
`specs/001-ome-zarr-sam-masking/contracts/cli.md`'s prompt-file-format section -- the same
cross-feature doc-alignment pattern feature 003 used). `interactive.py` needs no change: it always
routes prompts through `OrganMaskPredictor`, so the `api.py` stamp covers it.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Code Quality**: One small, well-named conversion method added where the existing `Prompt`/
  `PromptSet` model already lives; no new abstraction layer, no dead code. The on-disk file schema
  and the in-memory `to_record()` output are kept structurally symmetric (`{"level": ..., "objects":
  [...]}` both ways), avoiding a second, divergent shape. PASS.
- **II. Test Discipline (NON-NEGOTIABLE)**: Failing tests added first: cross-level reuse produces the
  same located mask (US1), anisotropic-axis conversion, old-format-file rejection (FR-007),
  unknown-authoring-level rejection (FR-008), out-of-bounds-after-conversion still raises (Edge
  Cases), and same-level/unset-level identity (FR-006, no regression). All 14 existing hand-written
  prompt-file fixtures across the test suite are updated to the new format so the full suite stays
  green. PASS.
- **III. Disciplined Version Control**: Atomic commits -- (1) `PromptSet.level` + conversion +
  file-format change + their direct unit tests, (2) pipeline wiring + the cross-level integration
  test, (3) `api.py`/`input_log.py` stamping + their tests, (4) the mechanical existing-fixture
  updates across the 14 files, (5) docs. Kept separate per Principle III; each left green. PASS.
- **IV. Performance Requirements**: Budget declared above (< 1 ms, no I/O); the same-level/unset
  identity shortcut is itself the regression guard for FR-006/SC-002 rather than a relied-upon "ratio
  happens to be 1.0" computation. PASS.

No violations. Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/008-level-agnostic-prompts/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
│   └── prompt-file-format.md
├── checklists/
│   └── requirements.md
├── spec.md
└── tasks.md              # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
src/organ_masker_lite/
├── prompts/
│   └── model.py             # CHANGED: PromptSet.level field; physical conversion method;
│                             #          load_prompt_file requires "level"; to_record() wraps
│                             #          {"level", "objects"}
├── engine/
│   └── pipeline.py           # CHANGED: convert prompts to the run level's grid before validate();
│                             #          raise a clear error when the authoring level doesn't exist
├── api.py                    # CHANGED: predict() stamps PromptSet(level=self._level)
├── input_log.py              # CHANGED: record_prompts() logs the authoring level
└── interactive.py            # UNCHANGED: already routes through OrganMaskPredictor

tests/
├── unit/
│   └── test_prompts.py                    # EXTENDED: conversion, rejection, identity cases
├── integration/
│   └── test_us3_levels.py                 # EXTENDED: author-at-one-level/run-at-another scenario
├── conftest.py                            # EXTENDED: optional per-axis scale in write_ome_zarr
└── (14 files with hand-written prompt-file JSON)  # MECHANICAL: add the required "level" key

README.md                                  # CHANGED: prompt-file example gains "level"
specs/001-ome-zarr-sam-masking/{data-model.md,contracts/cli.md}
                                            # CHANGED: align Prompt/PromptSet fields and the
                                            #          prompt-file-format section with the new field
```

**Structure Decision**: Existing single-project layout is retained. The behavioral change is confined
to the prompt model and its one call site in the pipeline; `api.py`/`input_log.py` get one-line
stamps each. No new module, no new project.

## Complexity Tracking

No constitution violations; table not required.
