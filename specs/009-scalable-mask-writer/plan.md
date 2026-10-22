# Implementation Plan: Scalable Mask Writer

**Branch**: `009-scalable-mask-writer` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-scalable-mask-writer/spec.md`

## Summary

`io/writer.py::write_mask` builds every pyramid level as a full in-memory NumPy array
(`_nn_resize` per level) and stores each level as one uncompressed whole-level chunk. On the
reported input this needed ~370 GB of RAM and 391 GB of disk (GitHub issue #3). This feature
rewrites the writer to work one **shard** at a time:

- Each output level is a sharded Zarr v3 array with a blosc(zstd, bitshuffle) compressor and
  `fill_value=0`. Its chunk/shard shape is copied from the matching input level when that level is
  sharded, and otherwise is the default 64³ chunks in 1024³ shards, with each shard axis rounded
  up to a multiple of 64 and capped at the level's size.
- Each shard's block is computed straight from the small run-level mask by **physical nearest
  neighbour**: each target voxel's centre is mapped through the level's scale+translation into the
  run level, with exact ties going to the lower index (clarification, research R2). This fixes
  today's one-voxel drift on non-exact ratios (6–25% of planes on the DANDI pyramid) and is unchanged
  for translation-free, exact-ratio inputs. The block is written as one aligned shard and dropped
  right away.
- A stdlib `ThreadPoolExecutor` writes shards in parallel. The default worker count fits an 8 GiB
  budget (2× shard bytes per worker, at least 1, at most the CPU count). An optional user-set
  `workers` (CLI `--workers`, API `MaskResult.save(workers=...)`) overrides it.
- All-background shards cost nothing, because zarr skips empty chunks by default.
- The OME metadata path (`Image.new` + `to_zarr`) is unchanged; it just receives sharded array
  specs. The temp-dir-then-rename atomic write is kept.
- The run record gains each level's layout. Per-level progress and worker counts go through the
  existing progress callback and, for CLI runs, the input log.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged).

**Primary Dependencies**: `zarr>=3` (sharding codec, `BloscCodec`, `write_empty_chunks=False`
default; probed on 3.3.0), `numcodecs` (blosc, already a zarr dependency), `ome-zarr-models>=1.6`
(unchanged metadata path), `numpy`; stdlib `concurrent.futures`. **No new dependency**: dask is
installed in this venv only through napari (the `[interactive]` extra), and the thread pool gives
exact concurrency control (SC-006) without it (research R3).

**Storage**: Local OME-Zarr v0.5 stores (unchanged, local-only). On-disk layout changes from one
uncompressed chunk per level to sharded + compressed (intended; older outputs stay readable).

**Testing**: pytest. A new `tests/unit/test_writer_layout.py` covers layout choice, worker-count
resolution, validation, run-record layout and progress cadence. `tests/unit/test_writer.py` is
extended for FR-006. It compares against an independent brute-force physical-NN oracle on a
translation-free fixture (where it must also match a copy of today's `_nn_resize`, kept in the test
file and removed from `src/`) and on a small DANDI-style pyramid with half-pixel translations and
non-exact ratios. `tests/performance/test_writer_perf.py` covers the
memory bound (SC-001) and time (SC-005). CLI/API parity and logging tests get worker-count cases. Every test that writes output also runs
ome-zarr-models' own `validate` CLI and its in-process 0.5 parser (`tests/conftest.py::
assert_ome_zarr_models_valid`), independently of this project's `validate_ome_zarr` wrapper (FR-009).
No GPU/SAM2 is needed for the writer tests; they build masks directly.

**Target Platform**: Linux/macOS CLI and Python library (unchanged).

**Project Type**: Single project (library + CLI), layout under `src/organ_masker_lite/`.

**Performance Goals**:
- **Memory (SC-001/FR-002)**: during the write, peak memory ≤ run-level mask + budget (default
  8 GiB). Checked in tests with a scaled-down budget: a 32³ run-level mask written into a 512³
  finest level must peak at < 25% of that level's size.
- **Time (SC-005)**: on the reference fixture, writing must take ≤ 1.25× a legacy single-chunk
  writer that is kept in the performance test and timed in the same process (interleaved, median of
  5). There is no machine-specific constant, so the test is deterministic across machines
  (Constitution II).
- **Disk (SC-002)**: a mostly-background mask must take < 5% of its uncompressed size.

**Constraints**: Output voxel values follow physical nearest neighbour (FR-006), so they're unchanged
from today's writer for translation-free, exact-ratio inputs and corrected otherwise. The output must
pass the project's own `validate_ome_zarr` and `OmeZarrReader` (FR-009). The worker count stays out
of `RunConfig.to_record()`, so the run record is unaffected by it (FR-012) and CLI/API parity
holds. `--workers < 1` is rejected before anything is written (FR-011).

**Scale/Scope**: Rewrite of `src/organ_masker_lite/io/writer.py`. Small wiring in
`engine/pipeline.py` (`run_masking` passes `workers`/`progress` through), `cli.py` (`--workers`),
`api.py` (`MaskResult.save(workers=, progress=)`) and `input_log.py` (one per-level write line).
Docs: README, feature 001's CLI/API contracts. Interactive export is unchanged and uses the
automatic worker count.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Code Quality**: one module rewritten around three small pure helpers (layout choice,
  worker resolution, per-shard block computation) plus the write loop. No new dependency, no new
  abstraction layer; the old `_nn_resize` survives only as a test oracle. PASS.
- **II. Test Discipline (NON-NEGOTIABLE)**: failing tests come first for equivalence with the old
  writer, layout copy/default rules, empty-shard skipping, compression ratio, worker validation and
  resolution, the run-record layout block, progress cadence, and the memory bound. Existing writer,
  CLI, API and parity tests stay green. PASS.
- **III. Disciplined Version Control**: atomic commits, each kept green, following the task phases:
  (1) Setup + Foundational (oracles, fixture knobs, layout/index/spec helpers), (2) US1 (streaming
  budgeted writer, `--workers`/`save(workers=)`, progress/log, failure safety), (3) US2 (empty-shard
  skip, `output_layout`), (4) US3 (layout copying), (5) Polish (relative time test, docs). PASS.
- **IV. Performance Requirements**: memory, time and disk budgets are declared above and enforced
  by `tests/performance/test_writer_perf.py` (memory, time) and `tests/unit/test_writer.py` (disk).
  Time is measured relative to a legacy writer in the same process. PASS.

No violations. Complexity Tracking not required.

**Post-design re-check (after Phase 1)**: still PASS. The design adds one optional public parameter
in two places (`--workers`, `MaskResult.save(workers=, progress=)`), both required by the
clarified spec (FR-011, FR-013). No other new public surface.

## Project Structure

### Documentation (this feature)

```text
specs/009-scalable-mask-writer/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── cli.md
│   ├── python-api.md
│   └── output-store.md
├── checklists/
│   └── requirements.md
├── spec.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
src/organ_masker_lite/
├── io/
│   └── writer.py            # REWRITTEN: plan_layouts(), resolve_workers(), shard block
│                            #   computation, threaded sharded write; same write_mask() entry
├── engine/
│   └── pipeline.py          # CHANGED: run_masking(..., workers=None) passes workers/progress/
│                            #   on_level through to write_mask
├── api.py                   # CHANGED: MaskResult.save(..., *, workers=None, progress=None)
├── cli.py                   # CHANGED: `mask --workers N`; wires per-level info into the log
└── input_log.py             # CHANGED: InvocationLog.record_write_level(...)

tests/
├── unit/
│   ├── test_writer.py              # EXTENDED: physical-NN oracle (translation-free + DANDI-style), empty shards,
│   │                               #   compression, atomic write unchanged
│   └── test_writer_layout.py       # NEW: layout copy/default/rounding, worker resolution,
│                                   #   validation, run-record layout block, progress cadence
├── integration/
│   ├── test_api_cli_parity.py      # EXTENDED: different worker counts give identical records
│   └── test_log_cli.py             # EXTENDED: per-level write line in the input log
├── contract/
│   └── test_cli_mask.py            # EXTENDED: --workers accepted; --workers 0 rejected, no output
└── performance/
    └── test_writer_perf.py         # NEW: legacy-writer reference, memory bound (SC-001),
                                    #   time vs legacy in the same process (SC-005)

README.md                                      # CHANGED: --workers, output layout note
specs/001-ome-zarr-sam-masking/contracts/{cli.md,python-api.md}   # CHANGED: --workers, save()
```

**Structure Decision**: Existing single-project layout. The behavioural change lives in one module
(`io/writer.py`); the other source changes only pass `workers`/`progress` through and add logging.

## Complexity Tracking

No constitution violations; table not required.
