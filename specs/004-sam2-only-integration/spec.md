# Feature Specification: SAM2-Only Integration

**Feature Branch**: `004-sam2-only-integration`

**Created**: 2026-08-20

**Status**: Draft

**Input**: User description: "Repurpose the sam2 vs. sam3 workflow into a unique sam2 integration. remove sam3 from this project and simplify all the logics to low abstraction layer of sam2 commands" — refined in follow-up: no `--backend` flag/parameter of any kind (not even a boolean), no backend Protocol or registry; the test suite is converted from a deterministic CPU-only stand-in to exercising the real, GPU-powered SAM2 backend directly; file count is treated as a proxy for repository complexity, so removal is preferred over narrowing wherever a whole file's reason to exist goes away.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run masking with SAM2 as the only, unconditional path (Priority: P1)

As someone running the organ-masker-lite CLI or Python API, I want SAM2 to be the only thing that ever runs — no backend argument to pass, no backend field to set, nothing to select — so I can produce organ masks with the simplest possible interface and never hit a SAM3-shaped error (gated weight auth, missing tokenizer vocab) or a stale backend-name error either.

**Why this priority**: This is the direct, immediate value of the refactor — every other benefit (maintainability, GPU-real test coverage, docs) stems from SAM2 being unconditional rather than merely default.

**Independent Test**: Can be fully tested by running the CLI (and the Python API) against a sample OME-Zarr input and prompt set — there is no backend argument to omit or pass, since none exists. Attempting to pass one (`--backend anything`, `backend="anything"`) must fail immediately with a standard, unmistakable argument-validation error (not a custom "unknown backend" message, since there is no longer a backend-name concept at all).

**Acceptance Scenarios**:

1. **Given** a valid OME-Zarr input and prompt set, **When** the user runs the masking CLI, **Then** the system uses SAM2 directly with no backend-selection step anywhere in the call path.
2. **Given** a valid OME-Zarr input and prompt set, **When** the user calls the Python API's masking function, **Then** SAM2 is invoked directly; there is no `backend` constructor parameter to pass.
3. **Given** a command line that still includes an old `--backend <name>` flag, **When** the user runs it, **Then** the CLI rejects it immediately as an unrecognized argument (standard `argparse` behavior), rather than accepting it and erroring later inside the pipeline.

---

### User Story 2 - Maintain a codebase with no backend abstraction and tests that exercise what actually ships (Priority: P2)

As a maintainer of organ-masker-lite, I want the code to call SAM2 directly with no protocol, factory, or registry indirection standing between callers and SAM2, and I want the test suite to run against the real, GPU-powered SAM2 backend rather than a CPU-only deterministic stand-in, so what the tests verify is what actually ships, and there is less code and fewer files to read and maintain.

**Why this priority**: Reduces both runtime indirection and repository size (measured in file count, treated as a proxy for complexity), and closes the gap between what's tested and what runs in production; secondary to the direct user-facing simplification in P1 but is the core of the "low abstraction layer" request.

**Independent Test**: Can be tested independently by confirming the backend Protocol, factory, and registry no longer exist anywhere in the codebase (as files or as importable symbols), that `engine/pipeline.py` and `engine/sweep.py` call SAM2's own class directly, and that the test suite invokes that same real SAM2 path — no CPU-only stand-in remains — with a graceful, explicit skip only on machines where SAM2 itself cannot be constructed (no GPU/weights/torch).

**Acceptance Scenarios**:

1. **Given** the refactored codebase, **When** a maintainer searches for a backend protocol, factory, or registry (by class/function name or by file path), **Then** none are found; SAM2's adapter class is imported and constructed directly at every call site.
2. **Given** the refactored codebase, **When** a maintainer counts files under `src/organ_masker_lite/`, **Then** the count is lower than before this feature (the five-file `backends/` package collapses into one module).
3. **Given** the refactored codebase, **When** a maintainer runs the test suite on a machine with a working SAM2 install and GPU, **Then** the tests that exercise masking run the real SAM2 predictor end-to-end (not a stand-in).

---

### User Story 3 - Onboard from documentation without SAM3 confusion (Priority: P3)

As a new user reading the project README/quickstart, I want documentation that describes only SAM2, so I don't have to decide which backend to pick, download gated SAM3 weights, or configure a BPE tokenizer vocab the project no longer uses — and I should see no `--backend` flag documented at all, since it no longer exists.

**Why this priority**: Improves first-run experience but depends on P1/P2 being done first; purely documentation-facing.

**Independent Test**: Can be tested by reading the README/quickstart end-to-end and confirming it describes a single, unconditional SAM2 workflow, with no SAM3 sections, no `--backend` flag, and no gated-weight instructions.

**Acceptance Scenarios**:

1. **Given** the updated README, **When** a new user follows the setup instructions, **Then** they complete setup and a first masking run with no backend decision to make.
2. **Given** the updated README, **When** a user searches the document for "SAM3" or `--backend`, **Then** no results are found.

---

### Edge Cases

- What happens when a script from before the refactor still passes `--backend <anything>` on the command line? `argparse` rejects it as an unrecognized argument (standard CLI behavior for a removed flag) — a clear, immediate, non-zero-exit failure, not a custom error message from application code.
- What happens when calling code from before the refactor still passes `backend=...` to `OrganMaskPredictor(...)` or `RunConfig(...)`? Both raise a standard `TypeError: unexpected keyword argument 'backend'` at call time, since the parameter no longer exists.
- What happens when the test suite runs on a machine without a GPU or without SAM2's weights available? Tests that require the real SAM2 backend are explicitly, individually skipped with a clear reason (not silently passed, and not hard-crashing the whole run) — this is the one piece of the old skip-guard machinery that is kept, because otherwise Constitution Principle II's "full test suite MUST pass" gate becomes unsatisfiable on any machine without a GPU. See Assumptions.
- What happens to SAM3-related environment variables (e.g., weight/tokenizer paths) still present in a user's environment after the refactor? They are simply unused and ignored; no cleanup is required.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST use SAM2 as its only segmentation implementation; no other model backend (including SAM3) may exist, be selectable, or be invoked.
- **FR-002**: The system MUST call SAM2 directly from every entry point (`cli.py`, `api.py`, `engine/pipeline.py`, `engine/sweep.py`) with no backend Protocol, factory, or name-registry standing between the entry point and SAM2.
- **FR-003**: The system MUST NOT expose a backend-selection parameter of any kind — no CLI flag (string or boolean), no constructor parameter, no config field. There is nothing to select.
- **FR-004**: An old `--backend`/`backend=` usage MUST fail via a standard argument/parameter-validation error (`argparse` unrecognized-argument, or `TypeError` for an unexpected keyword argument) rather than a custom "unknown backend" message, since the parameter itself no longer exists.
- **FR-005**: The system MUST remove all SAM3-specific logic, including gated-weights authentication handling and BPE tokenizer vocabulary resolution/download.
- **FR-006**: The system MUST remove the SAM3 optional installation path so installing the project never requires or offers SAM3 dependencies.
- **FR-007**: All project documentation (README, quickstart, contracts) MUST describe only SAM2, with no backend-selection instructions of any kind and no SAM3 material.
- **FR-008**: The automated test suite MUST exercise the real, GPU-powered SAM2 backend for masking behavior; no CPU-only deterministic stand-in backend may remain in the test suite.
- **FR-009**: For identical inputs, prompts, and SAM2 weights, masking output produced after this refactor MUST be identical to output produced by the SAM2 path before this refactor (pure refactor of the call path, not the model or its inputs).
- **FR-010**: Tests that require the real SAM2 backend MUST fail with an explicit skip (not a silent pass, and not an uncontrolled crash of the whole suite) on a machine where SAM2 cannot be constructed (no GPU, no weights, no `torch`/`sam2` install).

### Key Entities

- **SAM2 Segmentation Backend**: The sole segmentation implementation, called directly (no interface/abstraction) to produce organ masks from prompts and OME-Zarr input.
- **Legacy Backend-Selection Interface (removed)**: The former CLI flag, constructor parameter, config field, Protocol, and name-registry that let callers choose between backends or inject a stand-in; eliminated entirely by this feature.
- **Deterministic Stand-in Backend (removed)**: The former CPU-only, dependency-light test double (threshold + connected-component segmentation) used to keep the test suite fast and GPU-free; eliminated in favor of tests that exercise real SAM2.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can complete a full masking run (CLI or API) with no backend decision to make, and no backend-related flag or parameter exists to look up or misuse.
- **SC-002**: 100% of SAM3 references, and 100% of backend-selection abstraction (Protocol/factory/registry) references, are removed from source code, tests, documentation, and packaging metadata.
- **SC-003**: `src/organ_masker_lite/` has fewer files after this feature than before it (the `backends/` package, 5 files, collapses into 1 module).
- **SC-004**: For a fixed set of regression inputs, SAM2 masking output is unchanged before and after the refactor.
- **SC-005**: Documentation setup steps for a new user describe exactly one path: install SAM2, run. No backend-choice branching remains.
- **SC-006**: The test suite's masking-behavior tests run against real SAM2 end-to-end on a machine with GPU + weights available, with no deterministic stand-in remaining anywhere in the suite.

## Assumptions

- Organ-masker-lite is a pre-1.0 internal tool without a public SemVer compatibility guarantee, so removing the backend-selection interface entirely (rather than deprecating it) is acceptable. This is a breaking change for any caller that passed `backend=...`/`--backend ...` at all, including `backend="sam2"`.
- "Low abstraction layer of sam2 commands" is interpreted maximally: no Protocol, no factory, no registry, no injectable backend parameter anywhere — `engine/pipeline.py`/`engine/sweep.py` import and call one concrete SAM2 class directly. File count is used as a concrete, checkable proxy for this: the `backends/` package (`__init__.py`, `base.py`, `registry.py`, `sam2.py`, `sam3.py` — 5 files) collapses into a single `sam2.py` module at the top of the package.
- The test suite trades determinism/speed for fidelity: tests that previously ran fast and GPU-free against a stand-in now require a real GPU and SAM2 weights. This is a deliberate choice per explicit instruction ("focus on gpu-powered architectures including tests"), made because this project's target environment (an HPC cluster with GPU nodes) makes that assumption reasonable.
- One narrow piece of the old skip-guard machinery is kept, not because it's part of the "no-GPU test suite" being removed, but because Constitution Principle II (Test Discipline, NON-NEGOTIABLE) requires the full suite to be able to pass: GPU-dependent tests are marked and individually skipped with a clear reason on a machine where SAM2 cannot be constructed, rather than being deleted or left to hard-crash the run. This is a deliberately disclosed compromise — a maintainer who wants zero skip-guards (hard GPU requirement, no accommodation) can remove this later; it is called out explicitly rather than assumed away.
- This feature does not affect the in-flight OME-Zarr validation work (spec 003); that feature touches only input validation and is unrelated to backend selection.
- No data migration is required: this refactor does not touch stored masks or OME-Zarr data — only backend-selection code, the test suite's segmentation stand-in, docs, and packaging.
