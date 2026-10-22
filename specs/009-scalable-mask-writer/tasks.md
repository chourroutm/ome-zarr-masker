# Tasks: Scalable Mask Writer

**Input**: Design documents from `/specs/009-scalable-mask-writer/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (cli.md, python-api.md, output-store.md), quickstart.md

**Tests**: Per Constitution Principle II (NON-NEGOTIABLE), every behavioural change ships with tests
written to fail first. All test tasks below are required.

**Organization**: Grouped by user story (spec.md) after a Setup/Foundational base.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1/US2/US3; Setup, Foundational and Polish tasks carry no story label

## Path Conventions

Single project: `src/ome_zarr_masker/`, `tests/` at repository root.

---

## Phase 1: Setup (Oracles and Test Infrastructure)

**Purpose**: Reference implementations and fixture knobs the later tests compare against.

- [X] T001 Create `tests/performance/test_writer_perf.py` with a module docstring, a
  `_reference_fixture(tmp_path)` helper (3-level `write_ome_zarr` input whose finest level is 64×512×512,
  plus a run-level mask at level 1 with one cuboid of foreground), and `_legacy_write(output_path, mask,
  reader)`: today's algorithm, kept in the test file as the timing reference. It builds every level with
  `_reference_nn_resize` (imported from `tests/unit/test_writer.py`, T002) and stores each as one
  whole-level chunk with no compressor (`zarr.create_array(..., chunks=level_shape, compressors=None)`).
  No test function yet, and no hard-coded timing constant (SC-005 is measured relative to `_legacy_write`
  in the same process, see T032).
- [X] T002 In `tests/unit/test_writer.py`, add `_reference_nn_resize(mask, target_shape)` (a verbatim copy of
  today's `src/ome_zarr_masker/io/writer.py::_nn_resize`) and
  `_physical_nn_oracle(mask, src_scale, src_trans, dst_shape, dst_scale, dst_trans)`, which loops over every
  target index per axis, computes `x = (i*dst_scale + dst_trans - src_trans)/src_scale`, picks the nearest
  source centre with exact ties to the lower index (`i_src = floor(x)` if `x - floor(x) <= 0.5` else
  `floor(x) + 1`, clipped), and returns `mask[np.ix_(...)]`. Repoint the existing
  `test_nn_resize_preserves_labels_and_shape` at `_reference_nn_resize`, and stop importing `_nn_resize`
  from `ome_zarr_masker.io.writer`.
- [X] T003 Extend `tests/conftest.py::write_ome_zarr` with optional `chunks`, `shards`, `scales` and
  `translations` keyword arguments (all default `None`, which keeps today's behaviour: whole-array specs,
  `scales=[[f**i …]]`, `translations=[None]*n`). When `chunks`/`shards` are given, build each level's
  `ArraySpec` from an in-memory `zarr.create_array(..., chunks=, shards=)` template (shard/chunk capped to the
  level shape and rounded to keep shards a multiple of chunks). When `scales`/`translations` are given, pass
  them through to `Image.new`. Also add `assert_ome_zarr_models_valid(path)`. It runs ome-zarr-models'
  own `ome-zarr-models validate <path>` CLI (next to the interpreter) and requires exit 0 and
  "Valid OME-Zarr". It also opens the store in-process with `ome_zarr_models.open_ome_zarr(path,
  version="0.5")`, `ValidationWarning` promoted to an error, and requires a v0.5 `Image` back. Every test
  that writes output asserts it (FR-009), as an independent check alongside this project's
  `validate_ome_zarr` wrapper.

**Checkpoint**: Oracles, fixture knobs and the ome-zarr-models validation helper in place; suite still
green.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Layout planning, per-level index vectors and sharded/compressed array specs, which every story
uses. Pure helpers; `write_mask` itself is not rewritten yet.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T004 [P] Write failing unit tests in `tests/unit/test_writer_layout.py` for the default layout rule:
  `_default_layout((7526, 6985, 6985))` → chunks `(64,64,64)`, shards `(1024,1024,1024)`;
  `_default_layout((10, 100, 941))` → shards `(64, 128, 960)`; `_default_layout((941, 874, 874))` → shards
  `(960, 896, 896)`; `_shard_regions(layout)` yields slices that tile the level exactly once, including
  ragged edges (sum of region volumes == level volume, no overlaps).
- [X] T005 [P] Write failing unit tests in `tests/unit/test_writer.py` for
  `_nn_indices(src_shape, src_scale, src_trans, dst_shape, dst_scale, dst_trans)` (one int64 vector per
  axis): (a) translation-free exact ×2 down/up-sampling equals `_reference_nn_resize`'s indices;
  (b) DANDI-style half-pixel translations `(scale_N - scale_0)/2` with non-exact ratios (e.g. src 941 →
  dst 1747) equal `_physical_nn_oracle`; (c) identity when source and target are the same level;
  (d) an exact tie resolves to the lower index; (e) all indices fall in `[0, src_dim)`.
- [X] T006 Write a failing test in `tests/unit/test_writer_layout.py`: `_array_spec(layout, axes)` returns a
  pydantic_zarr `ArraySpec` whose codec chain is `sharding_indexed(chunk_shape=layout.chunks, codecs=[bytes,
  blosc(zstd, clevel=3, bitshuffle)])`, with `fill_value == 0`, dtype `uint8`, outer chunk grid ==
  `layout.shards`, and `dimension_names == axes`.
- [X] T007 Implement in `src/ome_zarr_masker/io/writer.py`: module constants `DEFAULT_CHUNKS = (64, 64,
  64)`, `DEFAULT_MAX_SHARD = 1024`, `WRITE_BUDGET_BYTES = 8 * 2**30`, `COMPRESSOR =
  BloscCodec(cname="zstd", clevel=3, shuffle="bitshuffle")`; a frozen `LevelLayout(level, shape, chunks,
  shards, source)` dataclass; `_default_layout(shape)`, `_shard_regions(layout)`, `_nn_indices(...)` per
  research R2, built on the existing `geometry.nearest_index` (target → run level) and clipped to
  `[0, src_dim)`, and `_array_spec(layout, axes)` built from an in-memory
  template array (research R5). Leave `write_mask`/`_nn_resize` untouched (makes T004–T006 pass).

**Checkpoint**: Helpers green; existing suite unchanged.

---

## Phase 3: User Story 1 - Mask a very large volume without running out of memory (Priority: P1) 🎯 MVP

**Goal**: `write_mask` streams shard by shard within a memory budget, with physically correct voxels,
optional worker override, progress, and unchanged failure safety.

**Independent Test**: Write a 32³ run-level mask into a pyramid whose finest level is 512³ under a scaled-down
budget, and confirm peak memory stays far below the level size while the voxels match the physical oracle.

### Tests for User Story 1

- [X] T008 [P] [US1] In `tests/unit/test_writer.py`, write failing tests that call `write_mask` and compare
  every output level against `_physical_nn_oracle`: (a) a translation-free 3-level fixture with run level 1
  (also equal to `_reference_nn_resize`); (b) a DANDI-style fixture (`write_ome_zarr(..., scales=...,
  translations=...)` with half-pixel translations and non-exact level shapes) with run level 2; plus
  `validate_ome_zarr` and `assert_ome_zarr_models_valid` passing on both outputs.
- [X] T009 [P] [US1] In `tests/unit/test_writer_layout.py`, write failing tests for
  `resolve_workers(workers, layout)`: `None` → `max(1, min(os.cpu_count(), WRITE_BUDGET_BYTES // (2 *
  prod(layout.shards))))`; `3` → `3`; `0`, `-1`, `1.5`, `"2"` → `WriterError`; a shard with
  `2 * shard_bytes > WRITE_BUDGET_BYTES` and `workers=None` → `1` plus a `UserWarning` (`pytest.warns`).
- [X] T010 [P] [US1] In `tests/unit/test_writer_layout.py`, write failing tests that (a) `write_mask(...,
  workers=0)` raises `WriterError` and creates neither the output nor `<output>.tmp`; (b) with `workers=2`
  the number of shard tasks running at once never exceeds 2 (monkeypatch `writer._write_shard` with a
  wrapper that tracks the active count under a lock and sleeps briefly) (SC-006).
- [X] T011 [P] [US1] In `tests/unit/test_writer_layout.py`, write failing tests that a `progress` callback
  gets one level-start message per level, matching
  `r"writing level \d+ .* (\d+) shards .* workers=(\d+) \((user|budget)\)"`, then at most 10 further
  messages per level (one per shard for levels with fewer than 10 shards). With `workers=3`, every
  level-start message says `workers=3 (user)` (FR-012 API path, C-W-API-3). `write_mask` prints nothing
  to stdout (`capsys`).
- [X] T012 [P] [US1] In `tests/performance/test_writer_perf.py`, add `test_write_memory_is_bounded`:
  monkeypatch `writer.WRITE_BUDGET_BYTES = 8 * 2**20` and `writer.DEFAULT_MAX_SHARD = 64`, write a 32³ run-level
  mask into a 2-level output whose level 0 is 512³ (`write_ome_zarr(..., n_levels=2)` with a 512³ level 0,
  run level 1 downscaled to 32³ via custom `axis_factors=(16,16,16)`), and assert the `tracemalloc` peak
  during `write_mask` is < 32 MiB (SC-001).
- [X] T013 [P] [US1] In `tests/contract/test_cli_mask.py`, write failing tests: `mask ... --workers 0` exits
  non-zero with a message mentioning `--workers` and leaves no OUTPUT (no SAM2 needed: argparse rejects it);
  with real SAM2 (`real_backend`), `--workers 2` produces an output identical to a run without
  `--workers` (all levels equal; `run_record.json` equal apart from `run_id`).
- [X] T014 [P] [US1] In `tests/integration/test_log_cli.py`, write a failing `real_backend` test: the input
  log has exactly one `write_level:` line per output level, each with `workers=<n> (budget)`, and with
  `--workers 2` each says `workers=2 (user)`.
- [X] T015 [P] [US1] In `tests/integration/test_api_cli_parity.py`, write a failing `real_backend` test:
  `MaskResult.save(path, workers=1)` and the CLI with `--workers 3` produce identical level arrays and
  identical `run_record.json` contents apart from `run_id`; `save(path, workers=0)` raises `WriterError`
  and `path` doesn't exist.
- [X] T016 [US1] In `tests/unit/test_writer.py` (after T008), write failing tests for failure safety
  (FR-008, C-OUT-8): monkeypatch `writer._write_shard` to raise `RuntimeError` on its 3rd call while
  writing a multi-shard level with `workers=2`. Assert (a) `write_mask` raises `RuntimeError` and
  neither `output` nor `output.tmp` exists; (b) with an existing output and `overwrite=True`, the same
  mid-write failure leaves the previous output intact and byte-identical.

### Implementation for User Story 1

- [X] T017 [US1] In `src/ome_zarr_masker/io/writer.py`, implement `resolve_workers(workers, layout)` per
  data-model.md (validation → `WriterError`; budget derivation; oversized-shard warning).
- [X] T018 [US1] Rewrite `write_mask` in `src/ome_zarr_masker/io/writer.py` as `write_mask(output_path, mask,
  run_level, reader, run_record, overwrite=False, *, workers=None, progress=None, on_level=None)`:
  - Validate `workers` first.
  - Keep the existing overwrite guard and the `.tmp` + rename atomicity.
  - Plan default layouts for every level with `plan_layouts(reader)` (default-only for now; US3 adds
    copying).
  - Create metadata with `Image.new(array_specs=[_array_spec(...)], ...)` and `to_zarr(tmp)`.
  - Per level:
    - Compute `_nn_indices` from `reader.level_transform(level)` and
      `reader.level_transform(run_level)` (translation already 0 when absent).
    - Resolve the worker count and call `on_level(layout, n_shards, workers, "user"|"budget")`.
    - Emit the level-start progress message (format per T011).
    - Run a `ThreadPoolExecutor(max_workers=workers)` over `_shard_regions(layout)`.
      `_write_shard(z, mask, idx, region)` calls `_build_block(mask, idx, region)` =
      `mask[np.ix_(idx_z[r], idx_y[r], idx_x[r])]` and assigns the block to the aligned region.
    - Emit progress at each 10% of shards.
    - On the first worker exception, cancel the remaining futures, shut the pool down, and re-raise.
      The existing `except` block removes `.tmp`, and the previous output is only replaced after
      success.
  - Write `run_record.json`, then rename.
  - Delete `_nn_resize` from `src/` (makes T008–T012 and T016 pass).
- [X] T019 [US1] In `src/ome_zarr_masker/engine/pipeline.py`, add `workers: int | None = None` and
  `on_level=None` to `run_masking` and pass `workers`, `progress` and `on_level` through to `write_mask`.
- [X] T020 [US1] In `src/ome_zarr_masker/api.py`, change `MaskResult.save` to `save(self, store_path,
  overwrite=False, *, workers=None, progress=None)` and forward both to `write_mask`; update its docstring
  per `contracts/python-api.md`.
- [X] T021 [US1] In `src/ome_zarr_masker/input_log.py`, add `InvocationLog.record_write_level(layout,
  n_shards, workers, workers_source)` emitting one `write_level: <i> shape=... chunks=... shards=...
  shards_total=<n> workers=<w> (<user|budget>) source=<input|default>` line (best-effort, like the other
  record methods).
- [X] T022 [US1] In `src/ome_zarr_masker/cli.py`, add `mask --workers` (argparse type rejecting values < 1
  with a clear message; default `None`; help text per `contracts/cli.md`), pass it to `run_masking(...,
  workers=args.workers, on_level=log.record_write_level)` (makes T013–T015 pass).

**Checkpoint**: US1 complete. Large pyramids write within the budget with physically correct voxels and
unchanged failure safety, and the MVP is shippable.

---

## Phase 4: User Story 2 - Get small output files that viewers can stream (Priority: P2)

**Goal**: Prove and tighten compression, empty-shard skipping and single-piece readability, and record each
level's layout in the run record.

**Independent Test**: Write a mostly-background mask, inspect its metadata and on-disk size, read one shard
alone, and check `run_record.json`'s `output_layout`.

### Tests for User Story 2

- [X] T023 [P] [US2] In `tests/unit/test_writer.py`, write failing tests:
  - (a) each level's `zarr.json` first codec is `sharding_indexed`, with inner `blosc` zstd/clevel
    3/bitshuffle and `fill_value` 0 (C-OUT-2); the all-zero and mostly-background outputs pass
    `assert_ome_zarr_models_valid`;
  - (b) an all-zero mask leaves each level directory with no `c/` data files (C-OUT-5);
  - (c) a mostly background mask's store is < 5% of its uncompressed bytes (SC-002);
  - (d) for a level larger than one shard, open it with `zarr.open_array` on a
    `zarr.storage.LocalStore` subclass whose `get` records requested keys, read one shard-aligned region,
    and assert the values are correct and exactly one data key under `c/` was requested (plus metadata)
    (SC-004).
- [X] T024 [P] [US2] In `tests/unit/test_writer_layout.py`, write a failing test that `run_record.json` has an
  `output_layout` list with one entry per level holding `level, shape, chunks, shards, compressor, source`,
  no key containing `worker`, and identical contents for `workers=1` and `workers=4` (FR-012).
- [X] T025 [P] [US2] In `tests/unit/test_writer_layout.py`, write a failing test that a shard whose source
  region has no foreground is skipped without building its block. Monkeypatch-wrap `writer._build_block`
  and count calls: the all-background half of the volume contributes zero calls, while `_write_shard` is
  still called once per shard.

### Implementation for User Story 2

- [X] T026 [US2] In `src/ome_zarr_masker/io/writer.py`, make `_write_shard` return early, before calling
  `_build_block`, when `mask[idx_z[r].min():idx_z[r].max()+1, ...]` has no foreground (research R4).
- [X] T027 [US2] In `src/ome_zarr_masker/io/writer.py`, add `run_record["output_layout"]` (data-model.md)
  to a copy of the run record before writing `run_record.json` (makes T023–T025 pass).

**Checkpoint**: US1 + US2 complete; outputs are small and viewer-friendly, and the layout is traceable.

---

## Phase 5: User Story 3 - Output layout consistent with the input's (Priority: P3)

**Goal**: Copy chunk/shard shapes from sharded input levels; unsharded inputs keep the default.

**Independent Test**: Write against a sharded input (non-default chunks/shards) and an unsharded one, and
compare each output level's `chunks`/`shards` and `output_layout[i].source`.

### Tests for User Story 3

- [X] T028 [P] [US3] In `tests/unit/test_reader.py`, write a failing test for a new
  `OmeZarrReader.level_storage(level) -> tuple[chunks, shards | None]` on a sharded fixture
  (`write_ome_zarr(..., chunks=(16,16,16), shards=(32,32,32))`) and on an unsharded one (`shards is None`).
- [X] T029 [P] [US3] In `tests/unit/test_writer_layout.py`, write failing tests: `plan_layouts` on the sharded
  fixture copies each level's chunks/shards with `source == "input"`; on the unsharded fixture it returns the
  default layout with `source == "default"`; the written output's level arrays report the same
  `.chunks`/`.shards` as the plan (C-OUT-3), and the output written from the sharded input passes
  `assert_ome_zarr_models_valid`.

### Implementation for User Story 3

- [X] T030 [US3] In `src/ome_zarr_masker/io/reader.py`, add `OmeZarrReader.level_storage(level)` returning
  `(arr.chunks, arr.shards)` from the level's zarr array (makes T028 pass).
- [X] T031 [US3] In `src/ome_zarr_masker/io/writer.py`, make `plan_layouts(reader)` copy
  `level_storage(i)` when `shards is not None`, falling back to `_default_layout` (makes T029 pass).

**Checkpoint**: All three stories complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T032 In `tests/performance/test_writer_perf.py`, add `test_write_time_within_legacy`. Interleave 5
  runs each of `_legacy_write` (T001) and `write_mask` on `_reference_fixture`, in the same process, then
  assert `median(write_mask) ≤ 1.25 × median(_legacy_write)` (SC-005). If it fails, profile and fix
  before proceeding (Constitution IV). Disk ratio (SC-002) is covered by T023(c).
- [X] T033 [P] Update `README.md`: document `--workers` in the CLI options table, the output layout (sharded,
  blosc zstd/bitshuffle, layout copied from sharded inputs), the physical nearest-neighbour resampling, and
  `MaskResult.save(workers=, progress=)` in the Python API section.
- [X] T034 [P] Update `specs/001-ome-zarr-sam-masking/contracts/cli.md` (add `--workers`) and
  `specs/001-ome-zarr-sam-masking/contracts/python-api.md` (`MaskResult.save` signature), pointing to
  `specs/009-scalable-mask-writer/contracts/`.
- [X] T035 Run `specs/009-scalable-mask-writer/quickstart.md` steps 1–5 and confirm each expected outcome.
- [X] T036 Full regression: `uv run ruff check src tests`, `uv run ruff format --check src tests` (scoped to
  `src`/`tests`, never `.`, so Markdown code blocks in other features' specs aren't reformatted), and
  `uv run pytest -q`, all green with no unexpected skips.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none. T001 depends on T002 (it imports `_reference_nn_resize`).
- **Foundational (Phase 2)**: depends on Setup; blocks all stories.
- **US1 (Phase 3)**: depends on Foundational. It is the MVP.
- **US2 (Phase 4)**: depends on US1's T018 (the rewritten `write_mask` with `_write_shard`/`_build_block`);
  its tests can be written in parallel with US1's.
- **US3 (Phase 5)**: depends on US1's T018 (`plan_layouts` is introduced there default-only); independent
  of US2.
- **Polish (Phase 6)**: after US1–US3.

### Within Each Phase

- Tests are written and confirmed failing before their implementation tasks.
- Same-file tasks are sequential: `tests/unit/test_writer.py` (T002 → T005 → T008 → T016 → T023),
  `tests/unit/test_writer_layout.py` (T004 → T006 → T009 → T010 → T011 → T024 → T025 → T029),
  `tests/performance/test_writer_perf.py` (T001 → T012 → T032),
  `src/ome_zarr_masker/io/writer.py` (T007 → T017 → T018 → T026 → T027 → T031).

### Parallel Opportunities

- Phase 2: T004 and T005 (different test files).
- US1 tests: T008, T012, T013, T014 and T015 touch different files and can be written in parallel (T009–T011
  share `test_writer_layout.py`, and T016 shares `test_writer.py` with T008, so those run in sequence).
- US1 implementation: T019, T020 and T021 touch different files and can run in parallel once T018 lands; T022
  needs T019 and T021.
- US2 and US3 can proceed in parallel after T018.
- Polish: T033 and T034.

---

## Parallel Example: User Story 1 tests

```bash
Task: "Physical-NN equivalence tests for write_mask in tests/unit/test_writer.py"           # T008
Task: "Memory-bound test in tests/performance/test_writer_perf.py"                         # T012
Task: "--workers contract tests in tests/contract/test_cli_mask.py"                        # T013
Task: "write_level log lines test in tests/integration/test_log_cli.py"                    # T014
Task: "API/CLI parity with different worker counts in tests/integration/test_api_cli_parity.py"  # T015
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Setup (oracles, legacy timing reference, fixture knobs) → Foundational helpers.
2. US1: streaming, budgeted, physically correct writer + `--workers`/`save(workers=)` + progress/log +
   failure safety.
3. **STOP and VALIDATE**: memory-bound test, physical-oracle equivalence, failure safety, CLI/API parity.

### Incremental Delivery

1. US1 → large volumes write within budget (the issue's blocker).
2. US2 → empty-shard skipping, run-record layout, verified compression and partial reads.
3. US3 → layout copied from sharded inputs (matches DANDI / ome-zarr-tools pyramids).
4. Polish → relative time budget, docs, quickstart, full regression.

---

## Notes

- `real_backend`-marked tests need a constructable SAM2 (skipped otherwise), per this repo's convention.
- Writer unit/performance tests build masks directly and never need SAM2.
- Commit per plan.md's grouping, keeping every commit green (Constitution III).
