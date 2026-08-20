---

description: "Task list template for feature implementation"
---

# Tasks: SAM2-Only Integration

**Input**: Design documents from `/specs/004-sam2-only-integration/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present, revised 2026-08-20 per user follow-up — see each doc's revision note)

**Tests**: Per Constitution Principle II (Test Discipline, NON-NEGOTIABLE), every behavioral change MUST include automated tests, written to fail first. This revision also changes *what kind* of tests: the CPU-only deterministic stand-in is deleted, and masking-behavior tests now exercise real, GPU-powered SAM2, marked `@pytest.mark.real_backend` and skip-guarded via a new `sam2_available()` helper so the suite stays passable on a machine without a GPU.

**Organization**: Tasks are grouped by user story per spec.md's priorities (P1, P2, P3), but note the Dependencies section below — the Foundational phase here is unusually large because removing the `backend` parameter from `config.py`/`cli.py`/`api.py` immediately breaks ~22 other test files that reference it, so those conversions are not independently deferrable work; they are part of keeping the repository buildable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no unmet dependency)
- **[Story]**: Which user story this task belongs to (US1, US2, US3); omitted for Setup/Foundational/Polish
- Every task below has an exact repo-relative file path

## Path Conventions

Single project: `src/organ_masker_lite/`, `tests/` at repository root.

---

## Phase 1: Setup

- [ ] T001 Run `pytest -q` at the repo root and record the pass/fail/skip count as the pre-change baseline (no files modified; used for comparison in T042)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Delete the backend Protocol/registry, collapse `backends/` into one module, remove
every `backend` parameter, and convert every test that depended on the CPU-only stand-in — all of
this must land together, since removing the parameter breaks any test file still passing it.

**⚠️ CRITICAL**: No user story work should begin until this phase is complete. Per Constitution
Principle III, commit this phase as one coherent change (or a tightly-sequenced series ending green)
rather than in a state where the parameter is gone but dependent test files aren't yet updated.

### Tests + conversion, together (write the new regression assertion first, then remove the old stub usage in the same file/task)

- [X] T002 [P] In `tests/contract/test_cli_mask.py`: remove every `--backend` argument from existing CLI invocations; add a new test asserting `organ-masker-lite mask ... --backend anything` fails via `argparse`'s "unrecognized arguments" error (non-zero exit); mark masking-invocation tests `@pytest.mark.real_backend`
- [X] T003 [P] In `tests/contract/test_python_api.py`: remove every `backend=` argument from existing calls; delete `test_c_api_7_sam3_backend_runs_same_flow` and its `_HAVE_SAM3`/`real_backend_available("sam3")` gate; add a new test asserting `OrganMaskPredictor(backend="sam3")` raises `TypeError` naming the unexpected `backend` keyword; mark masking tests `@pytest.mark.real_backend`

### Source implementation

- [X] T004 [P] Move `src/organ_masker_lite/backends/sam2.py` to `src/organ_masker_lite/sam2.py` (drop the `name = "sam2"` class attribute; change the `RunConfig(backend="sam2")` fallback in `__init__` to `RunConfig()`); delete the rest of `src/organ_masker_lite/backends/` (`__init__.py`, `base.py`, `registry.py`, `sam3.py`)
- [X] T005 [P] In `src/organ_masker_lite/engine/pipeline.py`: replace `from ..backends.base import VideoSegmenterBackend` / `from ..backends.registry import get_backend` with `from ..sam2 import Sam2Backend`; remove the `backend: VideoSegmenterBackend | None = None` parameter from `compute_mask` and `run_masking`; construct `Sam2Backend(config=config)` unconditionally, still wrapped in `try/except Exception as exc: raise PipelineError(str(exc)) from exc` (depends on T004)
- [X] T006 [P] In `src/organ_masker_lite/engine/sweep.py`: replace `from ..backends.base import VideoSegmenterBackend` with `from ..sam2 import Sam2Backend`; retype `run_sweep`'s `backend` parameter as `Sam2Backend` (depends on T004)
- [X] T007 [P] In `src/organ_masker_lite/config.py`: remove the `backend: str = "sam2"` field from `RunConfig`; change `to_record()` to emit a hardcoded `"backend": "sam2"` instead of `self.backend`
- [X] T008 [P] In `src/organ_masker_lite/cli.py`: remove the `--backend` argument from both the `mask` and `interactive` subparsers; remove `backend=args.backend` from the `RunConfig(...)` and `InteractiveSession(...)` construction calls
- [X] T009 [P] In `src/organ_masker_lite/api.py`: remove the `backend: str = "sam2"` parameter and `self._backend` from `OrganMaskPredictor.__init__`; remove the `"backend": self._backend` entry from the kwargs dict built in `predict()`
- [X] T010 [P] In `src/organ_masker_lite/interactive.py`: remove the `backend: str = "sam2"` parameter from `InteractiveSession.__init__` and from the call it forwards
- [X] T011 [P] Remove the `sam3 = ["torch", "sam3"]` line from `[project.optional-dependencies]` in `pyproject.toml`

### Remaining test-suite conversion (depends on T004-T011 landing; these files call the now-changed signatures)

- [X] T012 In `tests/conftest.py`: delete `StubBackend`, `StubBackendDilate`, the `stub_backend` fixture, the `register_backend` import and both `register_backend(...)` calls; replace `real_backend_available(name: str)` with a no-argument `sam2_available() -> bool` that tries constructing `Sam2Backend()` (from `organ_masker_lite.sam2`) and returns `False` on `ImportError`
- [X] T013 [P] In `tests/unit/test_config.py`: drop the `backend="sam2"` keyword from the `RunConfig(...)` constructor call (field removed; the `rec["backend"] == "sam2"` assertion is unaffected) (depends on T007)
- [X] T014 [P] In `tests/integration/test_api_cli_parity.py`: remove `--backend`/`backend=` usage; mark `@pytest.mark.real_backend`, skip-guarded via `sam2_available()` (depends on T012)
- [X] T015 [P] In `tests/integration/test_engine_smoke.py`: remove the `stub_backend` fixture parameter and `backend=stub_backend`/`backend="stub"` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T016 [P] In `tests/integration/test_log_api.py`: remove `backend="stub"` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T017 [P] In `tests/integration/test_log_besteffort.py`: remove `--backend`/`stub` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T018 [P] In `tests/integration/test_log_cli.py`: remove `--backend`/`stub` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T019 [P] In `tests/integration/test_log_cli_failure.py`: remove `--backend`/`stub` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T020 [P] In `tests/integration/test_log_cli_runid.py`: remove `--backend`/`stub` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T021 [P] In `tests/integration/test_log_options.py`: remove `--backend`/`stub` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T022 [P] In `tests/integration/test_log_prompts_cli.py`: remove `--backend`/`stub` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T023 [P] In `tests/integration/test_log_stdout_clean.py`: remove `--backend`/`stub` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T024 [P] In `tests/integration/test_us1_box.py`: remove the `stub_backend` fixture parameter and `backend=`/`"stub"` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T025 [P] In `tests/integration/test_us1_exclusion.py`: same conversion as T024 (depends on T012)
- [X] T026 [P] In `tests/integration/test_us1_single_point.py`: same conversion as T024 (depends on T012)
- [X] T027 [P] In `tests/integration/test_us2_bidirectional.py`: same conversion as T024 (depends on T012)
- [X] T028 [P] In `tests/integration/test_us2_multiaxis.py`: same conversion as T024 (depends on T012)
- [X] T029 [P] In `tests/integration/test_us3_level_speed.py`: same conversion as T024; note its docstring/timing assertions now measure real GPU runtime, not stub-CPU runtime (depends on T012)
- [X] T030 [P] In `tests/integration/test_us3_levels.py`: remove `--backend`, `"stub"` from the CLI `argv` list; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T031 [P] In `tests/integration/test_us5_postprocess.py`: remove `--backend`/`"stub"` usage; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T032 [P] In `tests/integration/test_us6_interactive.py`: remove `backend="stub"` from every `InteractiveSession(...)` call; mark `@pytest.mark.real_backend`, skip-guarded (the file already has one `real_backend`-marked test — bring the rest in line with it) (depends on T012)
- [X] T033 [P] In `tests/performance/test_benchmark.py`: remove the `RunConfig(backend="stub", ...)` and `backend=StubBackend()` usage; construct `RunConfig()` and let SAM2 run unconditionally; update the module docstring, which currently says the 512³-under-5-minutes-on-GPU budget is "out of scope for the stub suite" — after this change, this file is exactly what measures that budget; mark `@pytest.mark.real_backend`, skip-guarded (depends on T012)
- [X] T034 [P] Delete `tests/integration/test_backend_comparison.py` in full (both its stub-pair test and its SAM3 comparison test compare selectable backends; nothing is selectable anymore)
- [X] T035 [P] Delete `tests/integration/test_us1_sam2_smoke.py` in full (it existed to be the one real-SAM2 test while everything else used the stand-in; redundant now that every masking test does)

**Checkpoint**: `pytest` collects cleanly with no `ImportError`/`TypeError` from a removed `backend` parameter anywhere. On GPU hardware with SAM2 weights, `real_backend`-marked tests run and pass. Without GPU, they skip individually with a clear reason — the run as a whole still completes (T002/T003 pass either way, since they don't need a real backend). No `VideoSegmenterBackend`, `register_backend`, `get_backend`, or `BackendError` symbol exists anywhere in `src/` or `tests/`.

---

## Phase 3: User Story 1 - Run masking with SAM2 as the only, unconditional path (Priority: P1) 🎯 MVP

**Goal**: A caller using the CLI or Python API never has a backend argument to pass, and an old
`--backend`/`backend=` usage fails via a standard, unmistakable argument-validation error.

**Independent Test**: Run the CLI/API against a sample OME-Zarr input and prompt set with no
backend argument at all and confirm a mask is produced; run the same with an old `--backend`/
`backend=` usage and confirm a standard `argparse`/`TypeError` failure. (Verified by T002/T003,
delivered in Foundational.)

### Implementation for User Story 1

- [ ] T036 [US1] Confirm the default path (no backend argument of any kind) succeeds end-to-end against real SAM2 by re-running the converted masking tests (T014-T033) on GPU hardware; record the confirmation in the PR/commit description — no new file changes

**Checkpoint**: User Story 1 is fully functional and independently testable — the default path is
unconditional SAM2; any old backend usage fails clearly (T002, T003 passing).

---

## Phase 4: User Story 2 - Maintain a codebase with no backend abstraction and GPU-real tests (Priority: P2)

**Goal**: A maintainer finds no backend Protocol/factory/registry anywhere, and can see the file
count actually went down.

**Independent Test**: `grep -rn "VideoSegmenterBackend\|register_backend\|get_backend\|BackendError\|backends\."
src/ tests/` returns nothing; `src/organ_masker_lite/` has fewer files than before this feature.

### Implementation for User Story 2

- [X] T037 [US2] Run `grep -rn "VideoSegmenterBackend\|register_backend\|get_backend\|BackendError\|backends\." src/ tests/` and confirm zero matches (depends on T004-T012, T034, T035)
- [X] T038 [US2] Count files under `src/organ_masker_lite/` (e.g. `find src/organ_masker_lite -type f -name '*.py' | wc -l`) before vs. after this feature (via `git diff --stat` against the branch point) and confirm the count decreased by 4 (SC-003) (depends on T004)

**Checkpoint**: Zero backend-abstraction references anywhere. File count down as expected.

---

## Phase 5: User Story 3 - Onboard from documentation without SAM3 confusion (Priority: P3)

**Goal**: `README.md` describes only SAM2, with no `--backend` flag documented anywhere.

**Independent Test**: Read `README.md` end-to-end; searching it for "SAM3" or "--backend" returns
nothing.

### Implementation for User Story 3

- [X] T039 [US3] Remove the "### SAM3 backend" section from `README.md` (gated-weights paragraph, tokenizer-vocab paragraph, and the env var table rows for `HF_TOKEN`, `ORGAN_MASKER_SAM3_CHECKPOINT`, `ORGAN_MASKER_SAM3_BPE`, `ORGAN_MASKER_SAM3_BPE_URL`)
- [X] T040 [US3] In `README.md`: remove the `pip install -e ".[sam3]"` line, every remaining `--backend` mention (not narrowed — the flag is gone), the "SAM2 (default) and SAM3 as first-class, interchangeable backends" line, and the "SAM2/SAM3" phrasing in the feature summary and the real-backend test note (depends on T039 — same file)

**Checkpoint**: All three user stories independently functional. README documents one unconditional SAM2 workflow.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T041 Run `grep -rli sam3 src/ tests/ README.md pyproject.toml` project-wide and confirm zero results (SC-002; depends on T004-T011, T034, T035, T039-T040)
- [ ] T042 Run the full `pytest` suite (ideally on GPU hardware) and compare pass/skip counts against the T001 baseline; confirm no unexpected failures (SC-006)
- [ ] T043 Walk through `quickstart.md` steps 1-6 end-to-end and confirm each expected outcome (SC-001, SC-003, SC-004, SC-005)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: T002/T003 (new regression tests) can start immediately. T004,
  T007-T011 (source edits to different files) can start immediately and run in parallel. T005/T006
  depend on T004 (need the new `sam2.py` import path). T012 (conftest.py) should land after
  T004-T011 so it can reference the final signatures; T013-T035 depend on T012. **This entire phase
  is one blocking unit** — per Constitution Principle III, treat it as a single commit or a
  tightly-sequenced series ending green, since a partial land (e.g., T007 without T013) leaves a
  test file broken.
- **User Stories (Phase 3-5)**: All depend on Foundational (Phase 2) completion.
  - US1 (T036) is a verification-only checkpoint.
  - US2 (T037-T038) is a verification/audit of what Foundational already delivered.
  - US3 (T039-T040) is independent of US1/US2 (docs only) and can run fully in parallel with them.
- **Polish (Phase 6)**: Depends on every prior phase.

### Parallel Opportunities

- T002 and T003 (different files) — parallel.
- T004 and T007-T011 (different files, no shared dependency) — parallel.
- T005 and T006 (different files, both depend only on T004) — parallel once T004 lands.
- T013-T035 (23 different test files, all depending only on T012 plus the relevant source-side
  task) — parallel as a block once T004-T012 land.
- US2 and US3 phases — fully parallel with each other.

---

## Parallel Example: Foundational Phase, source edits

```bash
# Once T004 (sam2.py move) is done, fan out the rest of the source edits together:
Task: "engine/pipeline.py: direct Sam2Backend import/construction"
Task: "engine/sweep.py: direct Sam2Backend import/type"
Task: "config.py: remove RunConfig.backend field"
Task: "cli.py: remove --backend flag"
Task: "api.py: remove backend parameter"
Task: "interactive.py: remove backend parameter"
Task: "pyproject.toml: remove sam3 extra"
```

## Parallel Example: Foundational Phase, test conversions (after T012)

```bash
Task: "test_us1_box.py: drop stub, mark real_backend"
Task: "test_us1_exclusion.py: drop stub, mark real_backend"
Task: "test_us1_single_point.py: drop stub, mark real_backend"
Task: "test_us2_bidirectional.py: drop stub, mark real_backend"
Task: "test_us2_multiaxis.py: drop stub, mark real_backend"
# ... (all 22 files in T013-T033 are independent of each other)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001).
2. Complete Phase 2: Foundational (T002-T035) — large, but this alone delivers US1's entire
   user-facing behavior change and leaves the whole suite in a valid state.
3. Complete Phase 3: User Story 1 (T036, a confirmation checkpoint).
4. **STOP and VALIDATE**: run `pytest -m real_backend` on GPU hardware and confirm the converted
   tests pass; the MVP (SAM2-only, no-abstraction, GPU-real-tested behavior) is done at this point.

### Incremental Delivery

1. Setup + Foundational → SAM2-only behavior live, no abstraction layer, tests converted (MVP).
2. Add User Story 2 (T037-T038) → audit confirms zero abstraction references and lower file count.
3. Add User Story 3 (T039-T040) → docs are SAM3-free and `--backend`-free.
4. Polish (T041-T043) → whole-project confirmation, close out the feature.

---

## Notes

- Foundational carries no `[Story]` label on any task even though it delivers US1's behavior — US1's
  own phase (T036) is deliberately light because the behavior is already proven by Foundational.
- FR-009/SC-004 (byte-identical SAM2 output before/after) is validated manually via quickstart.md
  step 5, not by an automated pytest task.
- This feature deliberately trades a fast, hardware-independent test suite for one that verifies the
  real, shipped SAM2 path — see plan.md's Constitution Check and Complexity Tracking for the
  disclosed trade-off, and run T042 on GPU hardware to get real signal from this suite.
- Commit Foundational as one coherent unit (or a short green-ending sequence); commit US2/US3 separately.

## Execution status (2026-08-20)

T002-T035 and T037-T040 are implemented (all file edits complete; verified with `python3.12 -m
py_compile` across `src/` and `tests/` — no syntax errors — and manual review of every changed
call site). T037's grep and T038's file count were run directly and confirmed: zero
`VideoSegmenterBackend`/`register_backend`/`get_backend`/`BackendError`/`backends.` references
anywhere, and `src/organ_masker_lite/` file count went from 25 to 21 (−4, matching SC-003 exactly).

**Left unchecked, blocked on environment access this session does not have** (no Python
environment with the project's dependencies, and no GPU/SAM2 weights, are available here):
- **T001 / T042**: baseline and final `pytest` runs.
- **T036 / T043**: end-to-end confirmation against a real SAM2 install and the quickstart walkthrough.
- **T041**: the project-wide `grep -rli sam3` does **not** return zero — it still matches
  `tests/contract/test_cli_mask.py` and `tests/contract/test_python_api.py`, but only inside the
  two new regression tests (`test_backend_flag_rejected`, `test_c_api_8_backend_kwarg_rejected`)
  that assert the string `"sam3"` is now rejected. This is intentional (contracts/cli.md C-CLI-6,
  contracts/python-api.md C-API-8) and consistent with SC-002's intent (no SAM3 *support*
  remains), not an oversight — but it means T041 as literally worded ("confirm zero results")
  does not pass without this caveat.

All of the above require running on this project's GPU hardware; someone with that access should
run T001/T036/T041(re-check with the caveat above)/T042/T043 before merging.
