# Phase 0 Research: SAM2-Only Integration

No `NEEDS CLARIFICATION` markers remain in the Technical Context. This revision supersedes an
earlier version of this document: the first pass (see git history) recommended *keeping* the
backend Protocol/registry as a test-injection seam. Direct user follow-up overrode that: drop the
backend selector and registry entirely, drop the CPU-only ("no-GPU") test suite that seam existed
to support, focus tests on the real, GPU-powered SAM2 backend, and use file count as a concrete
proxy for repository complexity. This document reflects that final direction.

## Decision 1: Delete the SAM3 adapter and its gated-weights/tokenizer machinery outright

**Decision**: Delete `src/organ_masker_lite/backends/sam3.py` in full. Drop the `sam3`
optional-dependency extra from `pyproject.toml`.

**Rationale**: FR-001/FR-005/FR-006. Confirmed by `grep -rli sam3` that this is the only SAM3-specific
code in the project.

**Alternatives considered**: Deprecation window — rejected; no compatibility guarantee to serve
(pre-1.0 tool), and Constitution Principle I forbids dead code.

## Decision 2: Delete the backend Protocol and registry; collapse `backends/` into one module

**Decision**: Delete `src/organ_masker_lite/backends/` in full — `__init__.py`, `base.py`
(`VideoSegmenterBackend` Protocol), `registry.py` (`register_backend`/`get_backend`/
`available_backends`/`BackendError`), `sam2.py`, `sam3.py` (5 files). Create one new module,
`src/organ_masker_lite/sam2.py`, containing the SAM2 adapter class (unchanged internals, minus its
`name = "sam2"` class attribute, which only existed for registry lookup). `engine/pipeline.py` and
`engine/sweep.py` import this class directly and construct/type-hint against it — no Protocol, no
factory, no name string anywhere in the call path.

**Rationale**: This is a direct reversal of the previous plan's Decision 2, made per explicit
instruction: "drop the backend selector and registry," with file count as the complexity metric.
Five files collapsing into one is the concrete, checkable form of that instruction (SC-003). The
`name = "sam2"` attribute and the entire registry existed only to support two things this feature
also removes: (a) selecting among multiple *production* backends (SAM3 is gone), and (b) injecting
named test doubles (the CPU-only stand-in is gone — see Decision 3). With both gone, the registry
has no remaining caller.

**Naming note**: `src/organ_masker_lite/sam2.py` shares its name with the third-party `sam2` PyPI
package it imports (`from sam2.build_sam import build_sam2_video_predictor`). This is safe under
Python 3's absolute-import semantics — a bare `import sam2`/`from sam2...` inside
`organ_masker_lite/sam2.py` resolves to the top-level installed package, not to itself; only an
explicit relative import (`from . import sam2`) would self-reference. No import shadowing occurs.

**Alternatives considered**:
- *Keep `backends/sam2.py` in a package with just one file plus `__init__.py`.* Rejected: still two
  files and a directory for what is now a single class; flattening to one top-level module is
  strictly simpler by the stated metric.
- *Rename the class away from `Sam2Backend` (e.g., to a bare function).* Rejected as unnecessary
  churn — the class's internals (lazy `torch`/`sam2` import, checkpoint resolution, predictor
  caching, `segment_video`) are unchanged and already minimal; only its registry-facing surface
  (`name` attribute) is removed.

## Decision 3: Delete the CPU-only deterministic stand-in; convert masking tests to real SAM2

**Decision**: Delete `StubBackend`, `StubBackendDilate`, the `stub_backend` fixture, and the
`register_backend` calls from `tests/conftest.py`. Every test that previously injected the stand-in
(`backend="stub"`, `--backend stub`, `backend=stub_backend`) is rewritten to drop that
argument entirely — the parameter no longer exists — and now exercises the real SAM2 backend by
default. `tests/integration/test_backend_comparison.py` (both its stub-pair test and its SAM3
comparison test) is deleted outright: with no selector, there is nothing left to compare.
`tests/integration/test_us1_sam2_smoke.py` is also deleted: it existed specifically to be *the one*
test that ran real SAM2 while everything else used the stand-in; once every masking test does that,
it is a redundant, single-purpose file (file-count metric again).

**Rationale**: FR-008, SC-006, direct instruction ("drop the test suite that was designed for
no-gpu architectures. focus on gpu-powered architectures including tests"). The stand-in's entire
purpose was to let tests run fast and deterministic without GPU/`torch`/`sam2` installed — exactly
the thing being dropped.

**Kept, narrowly**: A single skip-guard helper (replacing `real_backend_available(name)` with a
no-argument `sam2_available()`) remains in `tests/conftest.py`, and the existing `real_backend`
pytest marker (already declared in `pyproject.toml`) is applied to every test that now needs the
real backend. This is *not* a re-introduction of the stand-in — it makes no segmentation decisions
and returns no mask; it only lets a test skip with a clear reason on a machine where SAM2 cannot be
constructed, so Constitution Principle II's "full test suite MUST pass" remains satisfiable outside
a GPU environment (a skip is a pass; a hard crash across ~20 files would not be). See spec.md
Assumptions for this being called out explicitly rather than assumed silently.

**Alternatives considered**:
- *No skip guard at all; tests hard-fail without GPU.* Considered, since it's the most literal
  reading of "focus on gpu-powered architectures." Not chosen because it makes Constitution
  Principle II's NON-NEGOTIABLE full-suite-passes gate impossible to satisfy on any non-GPU machine,
  which is a larger consequence than the instruction plainly asked for. Flagged for the user to
  override if a hard requirement (no accommodation at all) is actually what's wanted.
- *Keep the stand-in for logging/CLI-plumbing tests only (e.g. `test_log_cli.py`) since they don't
  test segmentation quality.* Rejected: it's still the CPU-only backend the instruction says to
  drop, and keeping it in even a few files means the abstraction (a backend that isn't SAM2) still
  exists somewhere in the test suite.

## Decision 4: `RunConfig.backend` field removed; run-record keeps a constant `"backend": "sam2"`

**Decision**: `RunConfig` (`config.py`) loses its `backend: str = "sam2"` field entirely.
`to_record()` still emits `"backend": "sam2"` as a hardcoded literal (not read from any field), for
run-record/provenance continuity (feature 002's logging depends on this record shape).

**Rationale**: FR-003 forbids any backend field, but the run-record's `"backend"` key is
consumed by existing logging/provenance tooling (feature 002) and by `tests/unit/test_config.py`'s
assertion `rec["backend"] == "sam2"`; keeping the key as a constant preserves that contract with
zero configurability, which is exactly the point.

## Decision 5: Documentation scope

**Decision**: Remove README's "### SAM3 backend" section entirely, the `pip install -e ".[sam3]"`
line, and now also the entire `--backend` row/mentions (not narrowed to "sam2 only" — the flag is
gone, not restricted).

**Rationale**: FR-007, SC-005.
