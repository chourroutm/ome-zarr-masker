---
description: "Task list for OME-Zarr Organ Masking with SAM"
---

# Tasks: OME-Zarr Organ Masking with SAM

**Input**: Design documents from `/specs/001-ome-zarr-sam-masking/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED. Per Constitution Principle II (Test Discipline, NON-NEGOTIABLE) and the explicit
request, behavioral tests are written FIRST and must fail before implementation. The three US1
features are ordered as directed: single point, then bounding box, then exclusion point.

**Organization**: Tasks are grouped by user story. A deterministic stub backend (no torch/GPU) lets
every engine/IO/prompt test run without weights; real-backend tasks are marked skip-if-unavailable.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: User story label (US1..US6) on user-story phases only

## Path Conventions

Single Python package, `src/` layout: `src/ome_zarr_masker/`, tests in `tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and tooling.

- [X] T001 Create package skeleton and `pyproject.toml` (name `ome-zarr-masker`, Python >=3.11, core deps `numpy`/`zarr>=3`/`ome-zarr-models`/`scipy`, extras `[sam2]`/`[sam3]`/`[interactive]`/`[dev]`) with `src/ome_zarr_masker/__init__.py`
- [X] T002 [P] Configure `ruff` (lint + format) and `pytest` in `pyproject.toml` and add `tests/__init__.py`
- [X] T003 [P] Add `.gitignore` entries for the default model directory `ome_zarr_masker_models/` and temp/intermediate working files
- [X] T004 [P] Create empty subpackages with `__init__.py`: `src/ome_zarr_masker/{io,prompts,backends,engine,postprocess}/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared engine, IO, prompts, config, and test harness that ALL user stories depend on.

**CRITICAL**: No user story work can begin until this phase is complete. Tests (T006-T015) are
written before their implementations (T016-T025) and must fail first.

- [X] T005 [P] Add synthetic OME-Zarr v0.5 fixture generator (tiny multiscale volume with a known foreground blob) and a deterministic stub `VideoSegmenterBackend` in `tests/conftest.py`
- [X] T006 [P] Unit test for SAM2-compatible prompt model (coords/labels `{0,1}`, box, validation, file round-trip) in `tests/unit/test_prompts.py`
- [X] T007 [P] Unit test for `RunConfig` + model-directory resolution (default `./ome_zarr_masker_models`, env/option override, `allow_download`) in `tests/unit/test_config.py`
- [X] T008 [P] Unit test for consensus combine (majority/union/intersection over a vote accumulator; majority tie `votes == n/2` resolves to background) in `tests/unit/test_combine.py`
- [X] T009 [P] Unit test for OME-Zarr reader (level enumeration, axes, lazy slice access) in `tests/unit/test_reader.py`
- [X] T010 [P] Unit test for writer building an output pyramid with the SAME level count as input, copied transforms, nearest-neighbor resample, atomic write in `tests/unit/test_writer.py`
- [X] T011 [P] Unit test for input validation invoking `ome-zarr-models validate` and mapping its exit code in `tests/unit/test_validate.py`
- [X] T012 [P] Unit test for frame normalization to uint8 RGB and memmap frame store in `tests/unit/test_frames.py`
- [X] T013 [P] Engine smoke test (stub backend): single-axis forward pipeline over a synthetic volume produces a non-empty mask with the same level count as input, in `tests/integration/test_engine_smoke.py`
- [X] T014 [P] Unit test for weight management: auto-download invoked on first use via an injected fetcher (mocked, no network); `allow_download=False` with missing weights raises a clear error; pre-placed weights are used as-is, in `tests/unit/test_weights.py`
- [X] T015 [P] Unit test: pipeline preflight raises a clear, actionable error when estimated intermediate size (frame memmap + vote accumulator) exceeds available disk, in `tests/unit/test_preflight.py`
- [X] T016 [P] Implement OME-Zarr v0.5 reader (multiscale levels, axes, lazy slice access) in `src/ome_zarr_masker/io/reader.py`
- [X] T017 [P] Implement input validation via `ome-zarr-models validate` subprocess in `src/ome_zarr_masker/io/validate.py`
- [X] T018 [P] Implement `Prompt`/`PromptSet` (SAM2 convention, validation, JSON file load/save) in `src/ome_zarr_masker/prompts/model.py`
- [X] T019 [P] Implement `RunConfig`, model-directory resolution, and weight resolution with an injectable downloader (auto-download on first use; `--no-download` raises a clear error when weights are absent) in `src/ome_zarr_masker/config.py` _(`RunConfig.resolve_weight` is the injectable seam; the SAM2 checkpoint and SAM3 BPE-vocab resolution both delegate to it)_
- [X] T020 [P] Define `VideoSegmenterBackend` protocol in `src/ome_zarr_masker/backends/base.py` and registry (default `sam2`) in `src/ome_zarr_masker/backends/registry.py`
- [X] T021 Implement frame normalization + memmap frame store in `src/ome_zarr_masker/engine/frames.py` (depends on T016)
- [X] T022 [P] Implement consensus combine via memmap vote accumulator (majority/union/intersection) in `src/ome_zarr_masker/engine/combine.py`
- [X] T023 Implement OME-Zarr v0.5 writer (single binary 0/1 foreground mask per FR-021; output pyramid matching input levels, transforms, nearest-neighbor resample, atomic temp-store move, embed run record) in `src/ome_zarr_masker/io/writer.py` (depends on T016)
- [X] T024 Implement single-axis forward sweep propagation through the backend protocol in `src/ome_zarr_masker/engine/sweep.py` (depends on T013, T020, T021)
- [X] T025 Implement pipeline orchestration (preflight intermediate-size/disk check -> validate -> sweep -> combine -> write) with a clear error when intermediates won't fit, in `src/ome_zarr_masker/engine/pipeline.py` (depends on T013, T016-T024)

**Checkpoint**: Foundation ready - the engine runs end-to-end with the stub backend.

---

## Phase 3: User Story 1 - One-shot masking from landmarks via CLI (Priority: P1) MVP

**Goal**: `ome-zarr-masker mask INPUT OUTPUT --prompts FILE` produces an OME-Zarr v0.5 mask from
landmark prompts, single axis forward, default backend SAM2.

**Independent Test**: Run the CLI on a synthetic volume with a fixed prompt file (stub backend) and
confirm a valid OME-Zarr v0.5 mask with the same level count as the input, no interactive steps.

### Tests for User Story 1 (write FIRST, must fail; in the directed order)

- [X] T026 [US1] Integration test: SINGLE-POSITIVE-POINT input yields a mask whose foreground includes the point, output level count equals input, in `tests/integration/test_us1_single_point.py`
- [X] T027 [US1] Integration test: BOUNDING-BOX input yields foreground predominantly within the box, in `tests/integration/test_us1_box.py`
- [X] T028 [US1] Integration test: EXCLUSION-POINT (label 0) removes the excluded region from the foreground, in `tests/integration/test_us1_exclusion.py`
- [X] T029 [P] [US1] CLI contract test (args schema, exit codes, overwrite guard, invalid input/level/prompts, `--no-download` with missing weights, no partial output) per `contracts/cli.md` in `tests/contract/test_cli_mask.py`

### Implementation for User Story 1

- [X] T030 [P] [US1] Implement SAM2 backend adapter (init_state, add_new_points_or_box, propagate_in_video) in `src/ome_zarr_masker/backends/sam2.py`
- [X] T031 [US1] Implement argparse `mask` command wiring prompt-file load -> pipeline -> write in `src/ome_zarr_masker/cli.py`
- [X] T032 [US1] Implement CLI error handling, exit codes, overwrite guard, and progress reporting in `src/ome_zarr_masker/cli.py` (depends on T031)
- [X] T033 [US1] Register console script `ome-zarr-masker` and `python -m ome_zarr_masker` in `pyproject.toml` and `src/ome_zarr_masker/__main__.py`
- [X] T034 [P] [US1] Real-SAM2 smoke integration test, marked skip-if-no-weights/GPU, in `tests/integration/test_us1_sam2_smoke.py`

**Checkpoint**: MVP complete - single point, box, and exclusion masking work via the CLI.

---

## Phase 4: SAM3 Backend & Comparison (Cross-Cutting)

**Purpose**: Add the second first-class backend (FR-018) and like-for-like comparison (SC-010). No
story label (not a numbered user story).

- [X] T035 Integration test: identical input/prompts via `--backend sam2` and `--backend sam3` both produce valid masks (comparison harness), in `tests/integration/test_backend_comparison.py`
- [X] T036 [P] Implement SAM3 backend adapter behind the `VideoSegmenterBackend` protocol in `src/ome_zarr_masker/backends/sam3.py`
- [X] T037 Register `sam3` in the backend registry and verify `--backend` selection end-to-end in `src/ome_zarr_masker/backends/registry.py`

**Checkpoint**: Both backends selectable and comparable.

---

## Phase 5: User Story 2 - Multi-axis sweeps and bidirectional propagation (Priority: P2)

**Goal**: Sweep along multiple axes and forward+reverse, combine into one consensus mask.

**Independent Test**: Multi-axis forward+reverse run has overlap >= single-axis forward-only run on
the synthetic volume with identical prompts.

### Tests for User Story 2 (write FIRST)

- [X] T038 [US2] Integration test: multi-axis majority consensus agreement >= single-axis result, with prompts placed on a single plane seeding the other axes' sweeps (FR-022), in `tests/integration/test_us2_multiaxis.py`
- [X] T039 [US2] Integration test: forward-and-reverse propagation merges both directions, in `tests/integration/test_us2_bidirectional.py`

### Implementation for User Story 2

- [X] T040 [US2] Extend `src/ome_zarr_masker/engine/sweep.py` with reverse propagation
- [X] T041 [US2] Extend `src/ome_zarr_masker/engine/pipeline.py` to sweep the prompted axis first, seed the non-prompted axes from its 3D mask (FR-022), then iterate axes x directions into the vote accumulator
- [X] T042 [US2] Wire `--axes` and `--direction` options in `src/ome_zarr_masker/cli.py`

**Checkpoint**: Multi-axis, bidirectional consensus masking available.

---

## Phase 6: User Story 3 - Choosing the resolution (binning) level (Priority: P2)

**Goal**: User selects a pyramid level; invalid level reports available levels and aborts; default
level is the coarsest (highest index).

**Independent Test**: Same prompts on two levels produce masks matching each level's grid; invalid
level aborts with the available list; coarser level is faster.

### Tests for User Story 3 (write FIRST)

- [X] T043 [US3] Integration test: valid level runs and output grid matches the level; missing level reports available levels and exits non-zero with no partial output; default (coarsest) level applied when unspecified, in `tests/integration/test_us3_levels.py`
- [X] T044 [US3] Integration test (slow-marked): coarser level end-to-end runtime < finer level on the same input, in `tests/integration/test_us3_level_speed.py`

### Implementation for User Story 3

- [X] T045 [US3] Implement level validation, coarsest-as-default selection, and available-levels reporting in `src/ome_zarr_masker/io/reader.py` and `src/ome_zarr_masker/config.py`, wired through `cli.py`

**Checkpoint**: Robust level selection.

---

## Phase 7: User Story 4 - Programmatic landmark API mirroring SAM (Priority: P3)

**Goal**: `OrganMaskPredictor` public API mirroring SAM (`set_volume`, `add_points`, `add_box`,
`predict`, `MaskResult.save`).

**Independent Test**: A short script produces a mask equal to the CLI output for identical
inputs/prompts; argument names/shapes match SAM2.

### Tests for User Story 4 (write FIRST)

- [X] T046 [US4] API contract test: signatures and behaviors C-API-1..9 (single point/box/exclusion, SAM-arg naming, validation errors) per `contracts/python-api.md` in `tests/contract/test_python_api.py`
- [X] T047 [US4] Integration test: API and CLI produce equivalent masks for identical inputs/prompts, in `tests/integration/test_api_cli_parity.py`

### Implementation for User Story 4

- [X] T048 [US4] Implement `OrganMaskPredictor` and `MaskResult` facade over the shared engine in `src/ome_zarr_masker/api.py`
- [X] T049 [US4] Export public API (`OrganMaskPredictor`, config types) from `src/ome_zarr_masker/__init__.py`

**Checkpoint**: SAM-like programmatic API at parity with the CLI.

---

## Phase 8: User Story 5 - Optional mask post-processing (Priority: P3)

**Goal**: Optional dilation/erosion/fill-holes with sensible defaults (fill-holes on, morphology
off), fully skippable.

**Independent Test**: Default post-processing reduces interior holes vs raw consensus; disabling
leaves the raw mask unchanged; explicit radii are applied exactly.

### Tests for User Story 5 (write FIRST)

- [X] T050 [US5] Integration test: default fill-holes reduces holes; `--no-fill-holes`/disabled leaves raw mask; `--dilate`/`--erode` apply exactly, in `tests/integration/test_us5_postprocess.py`

### Implementation for User Story 5

- [X] T051 [US5] Implement morphology (dilation/erosion/fill-holes via `scipy.ndimage`) in `src/ome_zarr_masker/postprocess/morphology.py`
- [X] T052 [US5] Wire post-processing into `src/ome_zarr_masker/engine/pipeline.py` with defaults, plus CLI/API flags in `cli.py` and `api.py`

**Checkpoint**: Optional post-processing with documented defaults.

---

## Phase 9: User Story 6 - Interactive masking session (Priority: P4)

**Goal**: napari session to view slices, place/adjust landmarks, preview, and export via the shared
engine.

**Independent Test**: Launch on a synthetic volume, place a positive and a negative landmark,
preview updates, export a valid OME-Zarr v0.5 mask.

### Tests for User Story 6 (write FIRST)

- [X] T053 [US6] Interactive session smoke test (marked skip-if-no-napari/display): place positive then negative landmark, preview updates, export valid OME-Zarr v0.5, in `tests/integration/test_us6_interactive.py`

### Implementation for User Story 6

- [X] T054 [US6] Implement napari interactive session calling the shared predictor/engine in `src/ome_zarr_masker/interactive.py`
- [X] T055 [US6] Add the `interactive` CLI subcommand (requires `[interactive]` extra) in `src/ome_zarr_masker/cli.py`

**Checkpoint**: All user stories functional.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T056 [P] Performance benchmark asserting plan.md targets (runtime on reference volume; peak RAM bounded and depth-independent; coarser level faster, SC-006) in `tests/performance/test_benchmark.py`
- [X] T057 [P] Write `README.md` with install (extras) and usage derived from `quickstart.md`
- [X] T058 [P] Type-hint/docstring pass and `ruff`/`ruff format` clean across `src/ome_zarr_masker/`
- [X] T059 [P] Document the run-record reproducibility format with an example in `docs/run-record.md`
- [X] T060 Execute the `quickstart.md` scenarios end-to-end as a final validation pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories. Tests T006-T015 precede impl T016-T025 (fail-first, including the engine smoke test T013 before sweep/pipeline T024-T025).
- **US1 (Phase 3)**: Depends on Foundational. The MVP.
- **SAM3 (Phase 4)**: Depends on US1 (reuses the backend protocol and CLI wiring).
- **US2 (Phase 5)**, **US3 (Phase 6)**: Depend on Foundational; independent of each other (both build on the US1 pipeline/CLI).
- **US4 (Phase 7)**: Depends on Foundational + US1 pipeline.
- **US5 (Phase 8)**: Depends on Foundational + US1 pipeline.
- **US6 (Phase 9)**: Depends on US4 (predictor) and US1 engine.
- **Polish (Phase 10)**: Depends on all targeted stories.

### Within Each User Story

- Tests written and failing before implementation (Constitution Principle II).
- Models/IO before services; engine before CLI/API wiring; story complete before next priority.

## Parallel Opportunities

- Setup: T002, T003, T004 in parallel after T001.
- Foundational tests T006-T015 all in parallel; impl T016-T020 and T022 in parallel (distinct files), then T021/T023 (need reader T016), then T024 (needs T013/T020/T021), then T025.
- US1: T026-T028 are ordered (shared fixtures, directed sequence); T029, T030, and T034 are [P].
- Different user stories (US2, US3) can be developed in parallel by different people once Foundational is done.

### Parallel Example: Foundational tests

```bash
# Launch foundational tests together (write-first):
Task: "Unit test for prompt model in tests/unit/test_prompts.py"
Task: "Unit test for RunConfig in tests/unit/test_config.py"
Task: "Unit test for combine in tests/unit/test_combine.py"
Task: "Unit test for reader in tests/unit/test_reader.py"
Task: "Unit test for writer pyramid matching in tests/unit/test_writer.py"
Task: "Unit test for validate subprocess in tests/unit/test_validate.py"
Task: "Unit test for frames in tests/unit/test_frames.py"
Task: "Engine smoke test in tests/integration/test_engine_smoke.py"
Task: "Weight management test in tests/unit/test_weights.py"
Task: "Preflight size/disk test in tests/unit/test_preflight.py"
```

## Implementation Strategy

### MVP First (User Story 1 only)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational).
2. Complete Phase 3 (US1): single point -> box -> exclusion, in that order, test-first.
3. STOP and VALIDATE: run the US1 integration tests and quickstart Scenarios 1-3.

### Incremental Delivery

1. Setup + Foundational -> engine runs with stub backend.
2. US1 -> MVP one-shot CLI masking (SAM2). Validate and demo.
3. SAM3 backend -> comparison capability.
4. US2 (multi-axis/bidirectional) -> quality. US3 (levels) -> speed/iteration control.
5. US4 (API) -> scripting/parity. US5 (post-processing) -> cleanup.
6. US6 (interactive) -> visual refinement.
7. Polish -> benchmark, docs, reproducibility.

## Notes

- [P] = different files, no dependency on incomplete tasks.
- Every behavioral task is preceded by a failing test (Principle II); commit after each task or
  logical group, keeping each commit green (Principle III).
- Real-backend tasks (SAM2/SAM3 smoke, benchmark) are skip-guarded so the suite runs without a GPU.
