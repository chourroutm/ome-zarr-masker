# Implementation Plan: Ordered Post-Processing Pipeline

**Branch**: `011-ordered-postprocessing` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/011-ordered-postprocessing/spec.md`

## Summary

The fixed post-processing options (`--fill-holes`, `--dilate`, `--erode`, `--invert`, applied in a
hard-coded order) are replaced by an ordered sequence of steps in one notation
(`close:3,fill,largest,margin:200um,invert`), given by `--postprocess`, `--postprocess-file`, the
steps saved in a prompt file, the Python API or the interactive panel. The approach:

- A new `postprocess/steps.py` parses the notation into immutable steps, resolves `default`
  against a prompt file's saved steps, and resolves radii to per-axis voxel radii from the run
  level's scale and axis units, all before segmentation (research R1, R2, R5).
- `postprocess/morphology.py` applies the steps in order. Dilation and erosion use an ellipsoidal
  ball (explicit structure for small shapes, a distance transform for large ones), slab by slab on
  a thread pool; `close` never removes and `open` never adds mask voxels at the volume edge
  (R3, R4).
- Prompt files gain an optional `"postprocess"` list. The interactive session loads and saves
  prompt files (`--prompts`), and gets a napari panel holding the current steps; saving writes the
  panel's final steps with the prompts (R5, R6).
- Run records and input logs list the resolved steps and their source (R7); the output keeps the
  input's axis units (R9).

## Technical Context

**Language/Version**: Python 3.11+ (unchanged).

**Primary Dependencies**: `scipy.ndimage` (`binary_dilation/erosion` with explicit structures,
`distance_transform_edt` with `sampling`, `binary_fill_holes`, `label`), `numpy`,
`ome-zarr-models` (`Axis(unit=...)`), napari/qtpy for the panel (existing `[interactive]` extra).
No new dependencies.

**Storage**: Prompt files (JSON, feature 008 format + optional `"postprocess"`); post-processing
files (JSON with `"postprocess"`); run records and input logs (updated shape). OME-Zarr output now
records axis units.

**Testing**: pytest. New `tests/unit/test_postprocess_steps.py` (notation, units, resolution,
precedence), rewritten `tests/unit/test_morphology.py` (each step vs a whole-volume reference,
slab/thread equivalence, border rules, anisotropic physical radii), `tests/integration/
test_postprocess_prompts.py` (session ↔ prompt file ↔ `mask`, parity, reproducibility, with the
SAM2 stub), CLI cases in `tests/contract/test_cli_mask.py`, updated `test_us5_postprocess.py`,
`test_config.py` and the API contract tests, and a `slow` `tests/performance/
test_postprocess_perf.py`. The napari panel wiring itself is exercised through the session's
programmatic interface (the GUI layer stays untested, as the existing `launch`). A real-data
check outside the suite, `validation/dandi_001278_postprocess.py`, masks a small µCT asset of
dandiset 001278 remotely on a GPU node (quickstart step 8).

**Target Platform**: Linux/macOS CLI and library (unchanged).

**Project Type**: Single project (library + CLI).

**Performance Goals**:
- SC-006: `close:3,fill,largest,margin:3` on a 941 × 874 × 874 run-level mask in < 5 min on one
  compute node (estimate from R4: ≈ 1.5 min on 4 threads).
- Peak memory for post-processing ≤ 16 GiB at that size (slabs bound the distance-transform
  buffers; the mask itself is 0.7 GB as bool).
- Validation and parsing: no I/O beyond the prompt/post-processing files and the store metadata
  already read; errors before segmentation.
- No regression of existing budgets (writer perf, level speed): the writer change is metadata only.

**Constraints**: Results must be independent of slab size and thread count (tested). Morphology
threads default to `min(os.cpu_count(), 8)`.

**Scale/Scope**: About 9 source files touched (`config.py`, `cli.py`, `api.py`, `interactive.py`,
`engine/pipeline.py`, `prompts/model.py`, `io/reader.py`, `io/writer.py`, `postprocess/
morphology.py`), 1 new (`postprocess/steps.py`), plus README and `docs/run-record.md`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| I. Code Quality | One new module with documented public names; old options removed rather than kept dead (FR-010); the algorithm switch (structure vs distance transform) is the one deliberate complexity, justified by R4 measurements | PASS |
| II. Test Discipline | Each contract item (C-PP-*, C-CLI-PP-*, C-API-PP-*) maps to a test written first; morphology tested against a whole-volume reference; stub backend keeps tests offline and deterministic | PASS |
| III. Version Control | Planned commits: notation + units → morphology → pipeline/CLI/records → prompt files + interactive → docs; each green | PASS |
| IV. Performance | SC-006 time and memory targets declared; measured by a `slow` test on a compute node; R4 small-scale measurements back the algorithm choice | PASS |

Post-design re-check (after Phase 1): PASS. The removal of the old options is a deliberate,
user-requested break (no backward compatibility), recorded in the CLI contract.

## Project Structure

### Documentation (this feature)

```text
specs/011-ordered-postprocessing/
├── plan.md              # This file
├── research.md          # Phase 0: R1–R9
├── data-model.md        # Radius, PostProcessStep, PostProcessSpec, ResolvedStep, changes
├── quickstart.md        # Validation scenarios 1–7
├── contracts/
│   ├── postprocess-notation.md  # Grammar, steps, C-PP-1…5
│   ├── cli.md                   # Removed options, C-CLI-PP-1…5
│   └── python-api.md            # predict, InteractiveSession, C-API-PP-1…2
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/ome_zarr_masker/
├── postprocess/
│   ├── steps.py         # NEW: notation, Radius, PostProcessStep/Spec, resolve, PostProcessError
│   └── morphology.py    # apply_steps: ordered steps, ellipsoid balls, slabs + threads
├── config.py            # PostProcessConfig removed; RunConfig.postprocess: PostProcessSpec
├── prompts/model.py     # PromptSet.postprocess; load/save_prompt_file with "postprocess"
├── io/reader.py         # axis_units
├── io/writer.py         # output axes keep units
├── engine/pipeline.py   # resolve steps before segmentation; apply after consensus; record
├── api.py               # predict(postprocess=...)
├── interactive.py       # prompts_path load/save, set_postprocess, napari panel + "w" key
└── cli.py               # --postprocess/--postprocess-file; old flags removed; interactive --prompts

tests/
├── unit/test_postprocess_steps.py
├── unit/test_morphology.py            # rewritten
├── integration/test_postprocess_prompts.py
├── integration/test_us5_postprocess.py  # updated to the new notation
├── contract/test_cli_mask.py           # postprocess cases
└── performance/test_postprocess_perf.py  # slow, compute node

README.md, docs/run-record.md
```

**Structure Decision**: Single project, as before. Notation and resolution live next to the
morphology in `postprocess/`, so the CLI, API and session share one parser.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Two algorithms for dilation/erosion (explicit ball vs distance transform), chosen by shape size | Keeps every radius fast: balls are 2.7× faster at r=3, distance transforms 7× faster at r=8 and flat beyond (R4) | One algorithm only: either minutes per step at the large voxel radii that physical units produce on fine levels, or 2.7× slower at the common small radii; results are identical, and tests check both paths against the same reference |
