# Phase 0 Research: Invert Mask Output Option

No `NEEDS CLARIFICATION` markers remain in the Technical Context — this feature reuses the
project's existing language, dependencies, storage, and test tooling unchanged. The decisions below
formalize choices already made in `spec.md` (Assumptions / Clarifications) with their rationale and
rejected alternatives, as this phase requires.

## R1: Where inversion happens in the pipeline

**Decision**: Append inversion as the last step inside `postprocess_mask()`
(`src/organ_masker_lite/postprocess/morphology.py`), after dilate, erode, and fill-holes.

**Rationale**: FR-004 requires `--dilate`/`--erode`/`--fill-holes` to always act on the
organ-labeled region, never the inverted background. `postprocess_mask()` already owns "final mask
shaping" for a run, so extending it keeps that invariant enforced in exactly one place.

**Alternatives considered**:
- Invert immediately after `--combine`, before the morphology steps — rejected: dilating what is
  now background would erode the organ boundary in a way the morphology flags don't ask for, and
  would produce results a user could not predict from the documented flag semantics.
- Invert in `io/writer.py` at write time — rejected: `postprocess_mask` already owns final mask
  shaping; duplicating the ordering invariant into a second file (writer) would spread a single
  correctness rule across two modules instead of one.

## R2: CLI flag style — `store_true` vs. paired toggle

**Decision**: `--invert` is a plain `action="store_true"` flag, default off — the same style as
`--overwrite` and `--verbose`.

**Rationale**: `--fill-holes` uses `argparse.BooleanOptionalAction` specifically because its
default is *on*, so users need an explicit way to turn it off (`--no-fill-holes`). `--invert`'s
default is *off*; there is no scenario in this codebase where a default-off flag needs to be forced
back to off against some other default, so the simpler `store_true` form (already used by
`--overwrite`/`--verbose`) is the consistent choice.

**Alternatives considered**: `--invert`/`--no-invert` paired flag (`BooleanOptionalAction`) —
rejected as unneeded ceremony for a default-off flag.

## R3: Scope — `mask` only, not `interactive`

**Decision**: `--invert` is exposed only on the `mask` subcommand. `interactive.py`'s
`InteractiveSession.export()` path is untouched.

**Rationale**: Confirmed via `/speckit-clarify` (2026-08-26). `interactive.py`'s export path
already doesn't expose any of the other batch post-processing flags (`--dilate`, `--erode`,
`--fill-holes`, `--combine`) — it is a separate, GUI-driven flow. Scoping `--invert` the same way
keeps the two subcommands' capabilities consistent rather than introducing an inconsistency.

**Alternatives considered**: Adding an equivalent toggle to the interactive session's export step —
deferred as a possible follow-up feature; out of scope here (FR-008).

## R4: Performance — no new benchmark

**Decision**: No new performance test or budget is introduced.

**Rationale**: Inversion is a single `numpy` boolean negation over an array the pipeline has
already fully materialized in memory for the preceding fill-holes/dilate/erode steps — O(N) in
voxel count, no additional I/O. The existing `tests/performance/test_benchmark.py` budget (spec
001: 512³ volume masked in <5 minutes on GPU) measures the sweep/frame/SAM2-inference cost, which
this feature does not touch.

**Alternatives considered**: A microbenchmark asserting negation completes under some threshold —
rejected as testing `numpy` itself rather than this project's logic.

## R5: Test coverage — new fast unit test vs. GPU-gated integration test only

**Decision**: Add a new fast, GPU-free unit test module (`tests/unit/test_morphology.py`) that
calls `postprocess_mask()` directly with synthetic arrays to verify the invert step and its
ordering relative to dilate/erode/fill-holes, in addition to extending the existing
`real_backend`-gated `tests/integration/test_us5_postprocess.py` for the end-to-end case.

**Rationale**: `postprocess_mask()` currently has zero direct test coverage — it is only exercised
indirectly through the GPU-gated integration test, meaning the invert/ordering invariant would
otherwise be entirely untested on a machine without a GPU. Constitution Principle II requires the
full suite to pass everywhere; a skip is a pass, but skipping the *only* test of a new invariant
would leave it effectively unverified off-GPU.

**Alternatives considered**: Relying solely on the existing GPU-gated integration test — rejected,
leaves the core invariant unverifiable without a GPU/SAM2 install.
