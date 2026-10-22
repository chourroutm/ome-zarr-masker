# Implementation Plan: SAM2-Only Integration

**Branch**: `004-sam2-only-integration` | **Date**: 2026-08-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-sam2-only-integration/spec.md`

**Revision note**: This plan supersedes an earlier version. The first pass kept the backend
Protocol/registry as a test-injection seam for a CPU-only stand-in backend. Direct user follow-up
overrode that: drop the backend selector and registry entirely (not even a boolean flag), drop the
no-GPU test suite that seam existed to support, focus tests on the real GPU-powered SAM2 backend,
and treat file count as a concrete complexity metric. This version reflects that final direction.

## Summary

Repurpose ome-zarr-masker from a dual-backend (SAM2/SAM3), selectable-backend tool into a tool
where SAM2 is the only thing that ever runs, called directly with no abstraction layer at all. The
`backends/` package (`base.py` Protocol, `registry.py` factory/registry, `sam2.py`, `sam3.py`,
`__init__.py` — 5 files) is deleted and replaced by a single `src/ome_zarr_masker/sam2.py`
module. Every `--backend`/`backend=` surface (CLI flag, `RunConfig` field, `OrganMaskPredictor`/
`InteractiveSession` constructor parameter, and the `compute_mask`/`run_masking` object-injection
parameter) is removed outright — there is nothing to select, boolean or otherwise. The test suite's
CPU-only deterministic stand-in (`StubBackend`/`StubBackendDilate`) is deleted; the ~20 tests that
used it are converted to exercise the real, GPU-powered SAM2 backend, marked `real_backend`, with a
narrow skip guard (`sam2_available()`) kept only so the suite can still pass on a machine without a
GPU, per Constitution Principle II.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from spec 001)

**Primary Dependencies**:
- Core (unchanged, required): `numpy`, `zarr>=3`, `ome-zarr-models`, `scipy`.
- Optional extras: `[sam2]` -> `torch` + `sam2` (unchanged). `[sam3]` extra is **removed**.
  `[interactive]` -> `napari` (unchanged). `[dev]` -> `pytest`, `ruff` (unchanged).
- CLI: stdlib `argparse` (unchanged).

**Storage**: Unchanged from spec 001 — OME-Zarr v0.5 on local filesystem; on-disk memmap
intermediates; local model-weights directory for SAM2 checkpoints only.

**Testing**: `pytest`. This feature changes testing philosophy, not just code: masking-behavior
tests (integration/contract/performance) now exercise the real SAM2 predictor directly rather than
a CPU-only stand-in, marked `@pytest.mark.real_backend` (an existing marker in `pyproject.toml`)
and individually skipped via a `sam2_available()` guard on a machine without GPU/weights — this
guard is the one narrow piece of the old skip-guard machinery kept, required so Constitution
Principle II's "full suite MUST pass" gate stays satisfiable off-GPU (see spec.md Assumptions).
Backend-agnostic unit tests (`tests/unit/*` other than `test_config.py`'s one-line change) are
unaffected.

**Target Platform**: Unchanged from spec 001 — Linux/macOS workstation, single CUDA GPU (>= 8 GB)
recommended, CPU fallback supported. This feature's test-suite conversion makes the GPU path the one
actually exercised by CI/dev runs of the masking-behavior tests, on hardware where it's available
(e.g., this project's HPC GPU nodes).

**Project Type**: Single Python package (library + CLI + optional interactive viewer). Unchanged.

**Performance Goals** (Principle IV): No new performance target. `tests/performance/test_benchmark.py`
and `test_us3_level_speed.py` previously stated the real 512³-under-5-minutes-on-GPU budget was
"out of scope for the stub suite" — after this feature, running against real SAM2, they are exactly
what measures that budget, so the existing spec-001 target becomes actively checked by this suite
for the first time. FR-009: SAM2 output itself must be byte-identical before/after this refactor, so
no engine-level performance change is expected.

**Constraints**: Unchanged core constraints from spec 001 (no eager full-volume load, output level
count matches input, SAM2 prompt-encoder convention). New constraints from this feature: no code
path may import or reference `sam3`; no module may implement a backend-selection Protocol, factory,
or registry; installing/running the project MUST NOT require or offer a backend choice of any kind.

**Scale/Scope**: Same single-user, single-volume-per-run scope as spec 001. Scope of this feature:
delete 6 files (`backends/` package's 5 files + `test_backend_comparison.py`), add 1 file
(`sam2.py`), delete 1 more file (`test_us1_sam2_smoke.py`, now redundant), and edit roughly 25 other
files (`data-model.md`'s full inventory) — net file count in `src/ome_zarr_masker/` decreases by 4.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.0 (four core principles):

- **I. Code Quality Standards** — PASS. Net effect is deleting an entire abstraction layer (Protocol,
  factory, registry — 5 files) and a second ML backend, replacing them with one direct, minimal
  module. No unexplained magic values introduced; the file-count reduction is the concrete
  expression of "prefer the simplest solution that satisfies the requirement."
- **II. Test Discipline (NON-NEGOTIABLE)** — PASS, with a disclosed tension. Deleting the
  deterministic stand-in means the masking-behavior test suite now depends on real hardware (GPU +
  SAM2 weights) to actually execute its assertions, rather than running fast and deterministic
  everywhere. The "full suite MUST pass" gate is kept satisfiable by marking these tests
  `real_backend` and skipping them (not failing them) on a machine that can't construct SAM2 — a
  skip is a pass. This is a deliberate, user-directed trade of one reading of Test Discipline
  (fast, deterministic, hardware-independent) for another (tests verify what actually ships). Flagged
  explicitly in spec.md Assumptions and here rather than silently resolved.
- **III. Disciplined Version Control** — PASS (planned). Removal/conversion work decomposed into
  atomic commits (delete SAM3; collapse backends/ into sam2.py; remove backend params from
  config/cli/api/interactive; convert test files in logical groups), each leaving the suite green
  (accounting for `real_backend` skips where GPU is unavailable).
- **IV. Performance Requirements** — PASS. No performance target changes; if anything, this feature
  makes the existing spec-001 GPU performance budget actively measured for the first time (previously
  explicitly out of scope for the stub-based suite).

No unjustified violations. See Complexity Tracking for the disclosed Test Discipline trade-off,
recorded for visibility even though it is a deliberate, user-directed choice rather than an
oversight.

## Project Structure

### Documentation (this feature)

```text
specs/004-sam2-only-integration/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output (full removal/change inventory)
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI + Python API contract deltas)
│   ├── cli.md
│   └── python-api.md
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
src/ome_zarr_masker/
├── __init__.py
├── io/                       # unchanged (reader.py, writer.py, validate.py)
├── prompts/
│   └── model.py              # unchanged (SAM2-compatible convention already)
├── sam2.py                    # NEW: was backends/sam2.py; the entire backends/ package is deleted
├── engine/
│   ├── frames.py               # unchanged
│   ├── sweep.py                 # changed: imports Sam2Backend directly, no Protocol
│   ├── combine.py               # unchanged
│   └── pipeline.py              # changed: imports/constructs Sam2Backend directly; no backend= param
├── postprocess/
│   └── morphology.py          # unchanged
├── config.py                  # changed: RunConfig loses `backend` field; to_record() emits a constant
├── api.py                     # changed: OrganMaskPredictor loses `backend` parameter
├── cli.py                     # changed: `--backend` flag removed from both subcommands
├── interactive.py             # changed: InteractiveSession loses `backend` parameter
└── input_log.py                # unchanged (feature 002)

tests/
├── conftest.py                 # changed: StubBackend/StubBackendDilate/stub_backend/register_backend
│                                #          deleted; real_backend_available(name) -> sam2_available()
├── unit/                       # unchanged except test_config.py (drop backend= kwarg, 1 line)
├── contract/
│   ├── test_cli_mask.py         # changed: drop --backend usage, mark real_backend
│   └── test_python_api.py       # changed: drop backend= usage, mark real_backend; SAM3 test deleted
├── integration/
│   ├── test_backend_comparison.py  # DELETED (nothing left to compare)
│   ├── test_us1_sam2_smoke.py       # DELETED (redundant once all masking tests use real SAM2)
│   └── (~19 other test_*.py files)  # changed: drop stub injection, mark real_backend
└── performance/
    ├── test_benchmark.py         # changed: drop stub injection; now measures the real GPU budget
    └── test_log_overhead.py       # unchanged (backend mentioned only as inert log data)
```

**Structure Decision**: The `backends/` package is deleted and replaced by one top-level module
(`sam2.py`), collapsing the layer between entry points and SAM2 to nothing. `engine/pipeline.py`
(orchestration) and `engine/sweep.py` (per-axis segmentation) call that module's class directly.
`cli.py`/`api.py`/`interactive.py` lose their `backend` parameter entirely rather than narrowing it.
The single-engine-behind-three-entry-points structure from spec 001 is otherwise unchanged.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

No constitution violations. One trade-off is recorded here for visibility: deleting the
deterministic stand-in trades hardware-independent, always-fast test execution (one reading of
Constitution Principle II) for tests that verify the real, shipped SAM2 path (another reading of the
same principle — "tests demonstrate the intended behavior"). This was an explicit user instruction,
not a default this plan would have chosen unprompted (the prior version of this plan chose the
opposite trade-off, for the opposite reason).

| Item | Why Needed | Simpler Alternative Rejected Because |
|------|------------|--------------------------------------|
| `sam2_available()` skip guard (kept, narrowed from the old registry-based `real_backend_available(name)`) | Without any skip guard, ~20 tests would hard-fail (not skip) on any machine without a GPU/SAM2 weights, making Constitution Principle II's "full suite MUST pass" gate unsatisfiable off-GPU | Removing the guard entirely (hard GPU requirement, no accommodation) was considered — it's the more literal reading of "focus on gpu-powered architectures" — but rejected because it breaks a NON-NEGOTIABLE constitution gate outright rather than narrowing it; flagged in spec.md Assumptions for the user to override if a hard requirement is actually wanted |
