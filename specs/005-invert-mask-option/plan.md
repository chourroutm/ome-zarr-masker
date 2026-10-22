# Implementation Plan: Invert Mask Output Option

**Branch**: `005-invert-mask-option` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-invert-mask-option/spec.md`

## Summary

Add an `--invert` flag to the `mask` CLI subcommand that swaps the binary output mask's values
(organ voxels `1`/background `0` becomes organ `0`/background `1`). Inversion is applied as a new
final step in the existing `postprocess_mask()` function, after `--combine`, `--fill-holes`,
`--dilate`, and `--erode`, so morphological operations always act on the organ-labeled region
regardless of whether the caller wants the mask-in or mask-out shape written to disk. The
`interactive` subcommand's napari export path is untouched (clarified 2026-08-26).

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from spec 001)

**Primary Dependencies**: Unchanged — `numpy` (boolean negation of the already-materialized mask
array), `scipy` (unrelated to this change; already used by `postprocess_mask` for dilate/erode/
fill-holes). No new dependency.

**Storage**: Unchanged from spec 001 — OME-Zarr v0.5 on local filesystem. `--invert` does not
change the on-disk dtype/schema: the output stays `uint8` `{0,1}` (FR-005); `io/writer.py`'s
existing `(mask != 0).astype(np.uint8)` cast already handles an inverted boolean array correctly
with no code change.

**Testing**: `pytest`. `postprocess_mask()` currently has no fast, GPU-free direct test — it is
only exercised indirectly through `tests/integration/test_us5_postprocess.py`, which is
`real_backend`-gated (skipped without a GPU/SAM2 install). This feature adds a new fast unit test
for the invert step and ordering (no SAM2 needed), extends `tests/contract/test_cli_mask.py` for
the flag/help-text surface (also GPU-free), and extends the existing `real_backend`-gated
integration test for the end-to-end case.

**Target Platform**: Unchanged from spec 001 — Linux/macOS workstation, optional CUDA GPU.

**Project Type**: Single Python package (library + CLI + optional interactive viewer). Unchanged.

**Performance Goals** (Principle IV): No new performance target. Inversion is a single `numpy`
boolean negation over a mask array already fully materialized in memory by the preceding
fill-holes/dilate/erode steps — O(N) in voxel count, no extra I/O, no new allocation pattern.
`tests/performance/test_benchmark.py` measures the sweep/frame/SAM2-inference budget (spec 001:
512³ volume masked in <5 minutes on GPU), which this feature does not touch.

**Constraints**: Unchanged core constraints from spec 001. New constraint from this feature:
`--invert` MUST be scoped to the `mask` subcommand only — `interactive` must not accept or be
affected by it (FR-008, clarified 2026-08-26).

**Scale/Scope**: Same single-user, single-volume-per-run scope as spec 001. Scope of this feature:
1 new dataclass field (`PostProcessConfig.invert`), 1 changed function (`postprocess_mask`), 1 new
CLI flag plus its wiring, 1 changed serialization dict (`RunConfig.to_record()`), 1 new fast unit
test file, and small additions to 2 existing test files. No new modules, no dependency changes, no
files deleted.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.0 (four core principles):

- **I. Code Quality Standards** — PASS. One small, well-named boolean field and one matching CLI
  flag, added at the exact point (`postprocess_mask`'s end) that already owns "final mask shaping."
  No new abstraction, no magic values; `--invert` mirrors the existing `--overwrite`/`--verbose`
  `store_true` style rather than inventing a new flag pattern.
- **II. Test Discipline (NON-NEGOTIABLE)** — PASS. Adds the first fast, deterministic, GPU-free
  test of `postprocess_mask()` itself (today it has none — only indirect, `real_backend`-gated
  coverage), written and observed failing before the implementation lands, per the write-test-first
  workflow. The existing GPU-gated integration test is extended for the e2e case; the fast CLI
  contract test is extended for the flag surface. Full suite stays green (with the same
  `real_backend` skip behavior as before) on a machine without a GPU.
- **III. Disciplined Version Control** — PASS (planned). Work decomposed into atomic commits: (1)
  `PostProcessConfig.invert` field + `is_noop` + `to_record()`, (2) `postprocess_mask` invert step,
  (3) `--invert` CLI flag + wiring, (4) tests — each leaving the suite green.
- **IV. Performance Requirements** — PASS. No performance target changes; justified above under
  Performance Goals. The O(N) negation is bounded by the same full-mask memory footprint the
  existing dilate/erode/fill-holes steps already require, which the current budget already accounts
  for.

No unjustified violations. No Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/005-invert-mask-option/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (PostProcessConfig field change)
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI contract delta)
│   └── cli.md
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
src/ome_zarr_masker/
├── config.py                  # changed: PostProcessConfig gains `invert: bool = False`;
│                               #          is_noop and RunConfig.to_record() updated
├── postprocess/
│   └── morphology.py          # changed: postprocess_mask() applies invert last, after
│                               #          dilate/erode/fill_holes
├── cli.py                     # changed: `mask` subparser gains `--invert` (store_true);
│                               #          `interactive` subparser unchanged (FR-008)
├── io/writer.py                # unchanged: existing `!= 0` cast already handles an
│                               #             inverted boolean array correctly
└── interactive.py              # unchanged (FR-008, clarified 2026-08-26)

tests/
├── unit/
│   └── test_morphology.py     # NEW: fast, GPU-free test of postprocess_mask's invert
│                               #      step and its ordering relative to dilate/erode/fill_holes
├── contract/
│   └── test_cli_mask.py       # changed: --invert flag present in --help; `interactive
│                               #          --invert` rejected as unrecognized (C-CLI-9)
└── integration/
    └── test_us5_postprocess.py # changed: extend for the --invert end-to-end
                                 #          complement property (real_backend-gated)
```

**Structure Decision**: Invert lives entirely inside the existing `postprocess/morphology.py` /
`config.py` / `cli.py` triad that already implements `--fill-holes`/`--dilate`/`--erode` — no new
module, no new abstraction layer. This keeps the "final mask shaping" responsibility in the one
place that already owns it (`postprocess_mask`), consistent with the single-engine-behind-
three-entry-points structure from spec 001.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

No constitution violations; no entries required.
