# Phase 0 Research: Scalable Mask Writer

**Feature**: 009-scalable-mask-writer | **Date**: 2026-10-16

The spec had no `[NEEDS CLARIFICATION]` markers left after `/speckit-clarify` (5 questions). This
phase settles the technical choices by **probing the installed libraries directly** (zarr 3.3.0,
numcodecs 0.16.5, numpy 2.5.2, ome-zarr-models 1.7), plus ome-zarr-tools' `apply_mask` (dask
2026.7.1). The probe scripts lived in the session scratchpad; their key results are quoted here.

## R1: Storage layout per level

**Decision**: Every output level is a Zarr v3 array with the `sharding_indexed` codec,
`fill_value=0`, dtype `uint8`, and inner codecs `bytes` + `blosc(cname=zstd, clevel=3,
shuffle=bitshuffle)`. Layout rule (clarification Q1):
- input level sharded (`zarr.Array.shards is not None`) → copy its `chunks` and `shards` exactly;
- otherwise → chunks `(64, 64, 64)`; shards `min(1024, roundup(dim, 64))` per axis.

**Rationale**:
- The layout is read through `zarr.Array.chunks` / `.shards`. `.shards` is `None` for unsharded
  arrays (probed).
- Shards rounded up past the array edge are accepted: shape `(10, 100, 941)` → shards
  `(64, 128, 960)` round-trips exactly (probed). Capping at the level size means small levels
  don't get oversized empty shards, and keeping a multiple of 64 satisfies the sharding codec's
  "shard divisible by chunk" rule.
- Compression: a 16 MiB mask-like block was stored in **3,870 bytes** (probed), well past SC-002's
  5% target.
- Only the chunk/shard *shapes* are copied from the input, never its codecs: the input is usually
  float32 image data, and its compressor suits that, not a binary mask.

**Alternatives considered**: always the default (rejected in clarification Q1); copying the input's
chunks when it is unsharded (clarification Q1 enforces sharding); also copying the input's codecs
(wrong data type and statistics).

## R2: Producing each shard without materializing a level

**Decision** (clarification, planning session): **physical nearest neighbour**. Per axis `a`, with
the target level's scale `st`/translation `tt` and the run level's `ss`/`ts` (scale 1, translation 0
when absent), and `src_dim = s`:

```
x   = (i * st + tt - ts) / ss                          # target voxel centre, in run-level voxel units
idx = clip(ceil(x - 0.5 - 1e-9), 0, s - 1)             # nearest source centre; exact tie -> lower index
```

The per-axis index vectors are computed once per level (length = level dimension; ≤ 7526 int64 for
the reported volume). Each shard's block is then `m[np.ix_(idx_z[r_z], idx_y[r_y], idx_x[r_x])]`, the
index vectors sliced to the shard region. This works for coarser and finer levels alike, and is the
identity for the run level itself.

**Rationale**:
- On the reported DANDI input (half-pixel translations `(scale_N − scale_0)/2`, the ome-zarr-tools /
  NGFF binning convention, and non-exact shape ratios such as 874 → 1747), today's top-left mapping
  `floor(i · s / t)` disagrees with the physically correct source voxel on 6.2% (level 0), 12.5%
  (level 1) and up to 25% (level 2, y) of index planes. The physical mapping is exact by
  construction (measured against the real DANDI transforms).
- The user's workaround mapping `floor((i + 0.5) · s / t)` matched the ground truth on every level
  of that pyramid, apart from exact ×2-downsample ties, where both candidates are inside the coarse
  voxel and equally valid.
- For translation-free pyramids (this project's own test fixtures) with exact ratios, the physical
  mapping reduces to today's mapping, so existing outputs there are unchanged.
- The output copies the input's transforms, so the voxels and the output metadata agree.
- The `1e-9` slack turns floating-point near-ties (e.g. `2j + 0.5 ± ulp`) into a deterministic rule
  (lower index) instead of rounding noise.
- Memory per block is one shard of uint8 plus three index vectors. Every level is derived from the
  run-level mask, never from another written level.

**Alternatives considered**: today's top-left mapping (wrong by one voxel on non-exact ratios);
shape-ratio centre mapping (the workaround; wrong for translation-free inputs, and ignores
translations that aren't exactly half a voxel).

**Shared implementation**: the formula already exists as `src/ome_zarr_masker/geometry.py::
nearest_index` (added when feature 008's prompt conversion was reworked onto the same rule), and
each level's `(scale, translation)` comes from `OmeZarrReader.level_transform(level)` (translation 0
when absent). The writer maps target indices `arange(dst_dim)` from the target level to the run level
with that helper and clips the result to `[0, src_dim)`.

**Oracles for tests**: an independent brute-force implementation that loops over voxel centres with
`decimal`-free float math, compared on (a) translation-free fixtures, where it must also equal a copy
of the old `_nn_resize` kept in the test file, and (b) a small pyramid carrying DANDI-style half-pixel
translations and non-exact ratios.

## R3: Parallelism and the memory budget

**Decision**: stdlib `concurrent.futures.ThreadPoolExecutor`; each task computes one shard block and
writes it with an aligned `z[region] = block`. Default worker count:
`max(1, min(os.cpu_count(), BUDGET // (2 * shard_bytes)))`, where `BUDGET = 8 GiB` and
`shard_bytes = prod(shard_shape)` (uint8). It is computed per level, because copied layouts can
differ between levels. A user-set `workers` replaces it. If `2 * shard_bytes > BUDGET`, the level is
written with one worker and a `warnings.warn` says the budget can't be met (spec edge case). The
budget (`WRITE_BUDGET_BYTES`) and the default layout (`DEFAULT_CHUNKS`, `DEFAULT_MAX_SHARD`) are
module constants in `io/writer.py`. Tests scale them down with `monkeypatch`; no private parameters
are added to the public API.

**Rationale**:
- Concurrent aligned shard writes from threads are correct and do run in parallel: the same 8-shard
  write took 0.58 s with 1 worker, 0.35 s with 2, 0.27 s with 4 and 0.23 s with 8, with output
  identical to the full resize every time (probed on a 128-CPU node). Compression releases the GIL,
  so threads are enough.
- An aligned shard write peaked at **4.5 MiB of traced allocations for a 16 MiB shard**, on top of
  the block itself (probed with tracemalloc). The 2× factor covers the block plus encode buffers,
  with headroom for allocations tracemalloc can't see (blosc's C buffers).
- Aligned writes cover whole shards, so no task reads or rewrites another task's shard.

**Alternatives considered**:
- **dask** `map_blocks` + `da.store`, as the issue suggests. Rejected: dask is installed here only
  through napari (the optional `[interactive]` extra), so it would become a new core dependency,
  and its scheduler gives less direct control over concurrency (SC-006) than a bounded thread pool.
- **Processes**: the run-level mask would have to be pickled or shared per worker, for no gain,
  since compression already releases the GIL.

## R4: Empty storage units (FR-005)

**Decision**: rely on zarr's default `array.write_empty_chunks = False` (probed on 3.3.0). Writing an
all-zero block whose value equals `fill_value=0` stores nothing. A level where only one of two
shards had foreground stored a single shard file (probed). As an optimization, a shard is skipped
entirely when its source region has no foreground, so the block isn't even computed. The source
region is found from the same index vectors.

## R5: OME metadata, validation, atomicity

**Decision**: keep the existing `Image.new(array_specs=..., ...)` + `image.to_zarr(...)` path, with
specs built from in-memory template arrays (`ArraySpec.from_zarr(zarr.create_array(MemoryStore(),
..., shards=..., compressors=...))`). Keep the `.tmp` directory + rename and the
`run_record.json` write.

**Rationale**: probed. `to_zarr` emits `sharding_indexed` metadata, reopening gives the expected
`chunks`/`shards`, and the project's `validate_ome_zarr` and `OmeZarrReader` accept the store
(FR-009). No hand-written metadata is needed.

## R6: Where the worker count lives (FR-011, FR-012)

**Decision**:
- **CLI**: `mask --workers N` (optional, int ≥ 1, validated before anything is written). It is
  passed to `run_masking(..., workers=)` → `write_mask(..., workers=)`.
- **API**: `MaskResult.save(store_path, overwrite=False, *, workers=None, progress=None)`. Saving is
  where the write happens. `InteractiveSession.export` keeps calling `save` without them
  (automatic).
- `workers` is **not** a `RunConfig` field, so `config.to_record()` and the run record never see it.
  Runs that differ only in worker count have identical run records (spec edge case), and the
  CLI/API parity test keeps comparing records for equality.
- **Logging**: `--workers` already shows up in the CLI log's `arguments:` block, through the
  existing `_loggable_args`. The *effective* per-level count is logged by a new
  `InvocationLog.record_write_level(level, shape, chunks, shards, n_shards, workers, source)` line,
  fed by a `write_mask(..., on_level=...)` observer that the CLI wires to the log. API saves run
  after `predict()`'s log has closed, so they report it through the progress callback (spec FR-012
  amended accordingly).

## R7: Progress cadence (FR-013)

**Decision**: when a level starts, `progress("writing level {i} {shape}: {n} shards
({chunks}/{shards}, {workers} workers)")`. Then a message each time completed shards cross the next
10% of `n` (at most 10 per level; levels with fewer than 10 shards report each shard). Messages go
only to the progress callback (stderr with `--verbose` in the CLI), never stdout.

## R8: Run-record layout block (FR-012)

**Decision**: `run_record["output_layout"] = [{"level": i, "shape": [...], "chunks": [...],
"shards": [...], "compressor": {"name": "blosc", "cname": "zstd", "clevel": 3, "shuffle":
"bitshuffle"}, "source": "input" | "default"}, ...]`. This is a new top-level key; existing keys are
unchanged. It is deterministic for a given input, so parity holds.

## R9: Downstream compatibility (ome-zarr-tools `apply_mask`)

**Finding** (from running its real `apply_mask` on 8 volume/mask layout combinations): it pairs
levels by name, needs equal shapes at the paired level, and rechunks the product onto the volume's
own write grid (`_get_zarr_write_chunks` → shard shape) before writing. So any mask layout gives
correct values. A layout matching the volume is the cheapest to read. Today's single-chunk output
would force it to load a whole level at once. **Separate upstream bug**: it masks only one level
(the first name in the volume group's unsorted listing). To be reported to ome-zarr-tools; out of
scope here.

## R10: How the budgets are measured in tests

**Decision**:
- **Memory (SC-001)**: `tracemalloc` peak while writing a 32³ run-level mask into a 2-level output
  whose finest level is 512³ (128 MiB). `WRITE_BUDGET_BYTES` is monkeypatched to 8 MiB and
  `DEFAULT_MAX_SHARD` to 64, so shards are 64³. Assert peak < 32 MiB (25% of the level), far below
  a full-level materialization.
- **Time (SC-005)**: keep a legacy writer in the performance test (today's whole-level
  `_nn_resize` + single uncompressed chunk per level). Time it and the new `write_mask`, interleaved
  in the same process, on a fixed reference fixture (3 levels, finest 64×512×512, median of 5 each).
  Assert new ≤ 1.25 × legacy. An absolute constant measured once would vary by machine and make the
  test flaky (Constitution II); the same-process ratio doesn't.
- **Disk (SC-002)**: on-disk bytes of a mostly-background mask < 5% of its uncompressed size.
