# Phase 1 Data Model: SAM2-Only Integration

This feature does not introduce or modify any persisted/business data entities (no change to
OME-Zarr inputs/outputs, masks, or run configs on disk). The "entities" below are the code-level
constructs the spec's Key Entities section names, plus the exhaustive inventory of every file this
feature touches, since removal is the substance of this feature.

## Entity: SAM2 Segmentation Backend

| Aspect | Value |
|---|---|
| Type | `Sam2Backend` class, `src/organ_masker_lite/sam2.py` (new location; was `backends/sam2.py`) |
| Conforms to | No Protocol — called directly by type, no structural typing layer |
| Constructed by | `engine/pipeline.py`, unconditionally, no name/lookup involved |
| Interface | `segment_video(frames: np.ndarray, prompts: PromptSet) -> np.ndarray` — unchanged |

Internals unchanged (lazy `torch`/`sam2` import, checkpoint resolution via `RunConfig.resolve_weight`,
predictor caching). Only its registry-facing `name = "sam2"` attribute is removed.

## Entity: Legacy Backend-Selection Interface (removed)

| Aspect | Before | After |
|---|---|---|
| `src/organ_masker_lite/backends/` | 5 files: `__init__.py`, `base.py`, `registry.py`, `sam2.py`, `sam3.py` | Deleted; replaced by 1 file: `src/organ_masker_lite/sam2.py` |
| CLI `--backend` flag | Present (`mask` and `interactive` subcommands) | Removed entirely |
| `RunConfig.backend` field | `str = "sam2"` | Removed (run-record still emits a constant `"backend": "sam2"`) |
| `OrganMaskPredictor(backend=...)` | Present | Removed |
| `InteractiveSession(backend=...)` | Present | Removed |
| `compute_mask`/`run_masking(..., backend=...)` object-injection param | Present | Removed — SAM2 is constructed internally, unconditionally |
| `pyproject.toml` optional extras | `sam2`, `sam3` | `sam2` only |

## Entity: Deterministic Stand-in Backend (removed)

| Aspect | Before | After |
|---|---|---|
| `StubBackend`/`StubBackendDilate` (`tests/conftest.py`) | Two CPU-only test doubles | Deleted |
| `stub_backend` fixture | Present | Deleted |
| `register_backend("stub"/"stub_dilate", ...)` | Present | Deleted (registry itself is gone) |
| `real_backend_available(name)` | Generic, name-based | Replaced by no-argument `sam2_available()` — a skip-guard only, not a segmenter |

## Removal / Change Inventory

### Source (`src/organ_masker_lite/`)

| File | Change |
|---|---|
| `backends/__init__.py`, `backends/base.py`, `backends/registry.py`, `backends/sam3.py` | Delete |
| `backends/sam2.py` | Move to `sam2.py` (package top level); drop `name = "sam2"` attribute; `RunConfig(backend="sam2")` fallback in `__init__` becomes `RunConfig()` |
| `engine/pipeline.py` | Replace `from ..backends.base import VideoSegmenterBackend` / `from ..backends.registry import get_backend` with `from ..sam2 import Sam2Backend`. Remove the `backend: VideoSegmenterBackend \| None = None` parameter from `compute_mask`/`run_masking`; construct `Sam2Backend(config=config)` unconditionally (still wrapped in `try/except` → `PipelineError` for a clean install-related error message) |
| `engine/sweep.py` | Replace `from ..backends.base import VideoSegmenterBackend` with `from ..sam2 import Sam2Backend`; retype `run_sweep`'s `backend` parameter as `Sam2Backend` |
| `config.py` | Remove `backend: str = "sam2"` field from `RunConfig`; `to_record()` emits a hardcoded `"backend": "sam2"` |
| `cli.py` | Remove `--backend` argument from both the `mask` and `interactive` subparsers; remove `backend=args.backend` from the `RunConfig(...)` and `InteractiveSession(...)` construction calls |
| `api.py` | Remove `backend: str = "sam2"` parameter and `self._backend` from `OrganMaskPredictor.__init__`; remove the `"backend": self._backend` entry from the kwargs dict built in `predict()` |
| `interactive.py` | Remove `backend: str = "sam2"` parameter from `InteractiveSession.__init__`; remove it from the call it forwards to |
| `pyproject.toml` | Remove `sam3 = ["torch", "sam3"]` line |
| `README.md` | Remove "### SAM3 backend" section, gated-weights/BPE env var rows, `pip install -e ".[sam3]"` line, and every `--backend` mention (not narrowed — removed) |

### Tests — no change needed (backend mentioned only as inert data, not selection)

| File | Why no change |
|---|---|
| `tests/unit/test_weights.py` | Docstring says "every backend" generically; no functional dependency |
| `tests/unit/test_input_log.py` | Uses `{"backend": "stub"}` only as arbitrary example log-record data, not an actual backend selection |
| `tests/performance/test_log_overhead.py` | Same — arbitrary example dict for exercising the logging subsystem |

### Tests — minor change

| File | Change |
|---|---|
| `tests/unit/test_config.py` | Drop `backend="sam2"` from the `RunConfig(...)` constructor call at line 30 (field removed); the assertion `rec["backend"] == "sam2"` at line 32 is unaffected (Decision 4's constant) |

### Tests — full rewrite (drop the stand-in; exercise real SAM2; add `real_backend` marker + `sam2_available()` skip guard)

All of these currently pass `backend="stub"` / `--backend stub` / an injected `stub_backend`/
`StubBackend()` object. The mechanical rule applied to every one: remove that argument entirely (the
parameter no longer exists), mark the test `@pytest.mark.real_backend`, and skip with
`sam2_available()` if not already guarded.

| File |
|---|
| `tests/contract/test_cli_mask.py` |
| `tests/contract/test_python_api.py` (also loses its already-planned SAM3 test) |
| `tests/integration/test_api_cli_parity.py` |
| `tests/integration/test_engine_smoke.py` |
| `tests/integration/test_log_api.py` |
| `tests/integration/test_log_besteffort.py` |
| `tests/integration/test_log_cli.py` |
| `tests/integration/test_log_cli_failure.py` |
| `tests/integration/test_log_cli_runid.py` |
| `tests/integration/test_log_options.py` |
| `tests/integration/test_log_prompts_cli.py` |
| `tests/integration/test_log_stdout_clean.py` |
| `tests/integration/test_us1_box.py` |
| `tests/integration/test_us1_exclusion.py` |
| `tests/integration/test_us1_single_point.py` |
| `tests/integration/test_us2_bidirectional.py` |
| `tests/integration/test_us2_multiaxis.py` |
| `tests/integration/test_us3_level_speed.py` |
| `tests/integration/test_us3_levels.py` |
| `tests/integration/test_us5_postprocess.py` |
| `tests/integration/test_us6_interactive.py` |
| `tests/performance/test_benchmark.py` (its docstring currently says the 512³-under-5-minutes-on-GPU budget is "out of scope for the stub suite" — after this change it is exactly what this file measures) |

### Tests — delete outright (redundant once every masking test uses real SAM2)

| File | Why |
|---|---|
| `tests/integration/test_backend_comparison.py` | Both tests (stub-vs-stub_dilate, SAM2-vs-SAM3) compare selectable backends; nothing left to select |
| `tests/integration/test_us1_sam2_smoke.py` | Existed to be *the one* real-SAM2 test while everything else used the stand-in; now redundant with every rewritten masking test |

### `tests/conftest.py`

| Change |
|---|
| Delete `StubBackend`, `StubBackendDilate`, the `stub_backend` fixture, `from organ_masker_lite.backends.registry import register_backend`, both `register_backend(...)` calls |
| Replace `real_backend_available(name: str)` with `sam2_available() -> bool`: try constructing `Sam2Backend()` (from `organ_masker_lite.sam2`), return `False` on `ImportError` |
| Keep unchanged: `write_ome_zarr`, `single_blob_zarr`, `two_blob_zarr` fixtures, `isolate_logs` autouse fixture |

## Validation rule carried over unchanged

- `Sam2Backend.__init__` continues to raise `ImportError` (wrapped by `engine/pipeline.py` into
  `PipelineError`) when `torch`/`sam2` cannot be imported — this existing error path is what
  `sam2_available()` probes for the skip guard; no new error-handling code is introduced.
