# Phase 1 Data Model: Scalable Mask Writer

**Feature**: 009-scalable-mask-writer | **Date**: 2026-10-16

Extends the output side of `specs/001-ome-zarr-sam-masking/data-model.md`. Nothing about inputs,
prompts or `RunConfig` changes.

## LevelLayout (new, internal to `io/writer.py`)

The storage plan for one output level, computed before anything is written.

| Field | Type | Notes |
|-------|------|-------|
| `level` | int | Level index (matches the input's dataset path `"0"`, `"1"`, …) |
| `shape` | tuple[int, int, int] | Copied from the input level (unchanged guarantee) |
| `chunks` | tuple[int, int, int] | Inner chunk shape |
| `shards` | tuple[int, int, int] | Shard shape; always present (output is always sharded) |
| `source` | `"input"` \| `"default"` | `"input"` when copied from a sharded input level |

Rules (FR-007, research R1):
- Input level sharded → `chunks`, `shards` = the input level's, `source="input"`.
- Otherwise → `chunks=(64, 64, 64)`, `shards[a] = min(1024, roundup(shape[a], 64))`,
  `source="default"`.
- `n_shards = prod(ceil(shape[a] / shards[a]))`; `shard_bytes = prod(shards)` (uint8).

## Worker resolution (new, internal)

| Input | Result |
|-------|--------|
| `workers=None` (default) | `max(1, min(cpu_count, BUDGET // (2 * shard_bytes)))` per level, then capped at that level's shard count (the reported, effective value); `BUDGET = 8 GiB` |
| `workers=N`, N ≥ 1 | `N` for every level (user takes responsibility for memory, FR-011) |
| `workers=N`, N < 1 (or not an int) | `WriterError` / CLI usage error **before** any output is created |

If `2 * shard_bytes > BUDGET` with `workers=None`: one worker, plus a warning that the budget can't
be met (spec edge case).

## Output store (changed on-disk shape)

| Item | Before | After |
|------|--------|-------|
| Level array codec chain | `bytes` only | `sharding_indexed(chunk_shape=chunks; codecs=[bytes, blosc(zstd, clevel 3, bitshuffle)])` |
| Level `chunk_grid` | whole level | `shards` (outer grid); `chunks` inside each shard |
| `fill_value` | default | `0`; all-background chunks/shards are not stored |
| Voxel values | top-left NN from run-level mask, `floor(i·s/t)` | **physical NN** using each level's scale+translation; ties → lower index (FR-006). Same as before for translation-free, exact-ratio inputs |
| Levels, shapes, axes, transforms | copied from input | unchanged |
| `run_record.json` | `run_id, input, level, config, prompts` | same keys **plus** `output_layout` |

### `run_record.json` → `output_layout` (new key, FR-012)

```json
"output_layout": [
  {"level": 0, "shape": [7526, 6985, 6985], "chunks": [64, 64, 64], "shards": [1024, 1024, 1024],
   "compressor": {"name": "blosc", "cname": "zstd", "clevel": 3, "shuffle": "bitshuffle"},
   "source": "default"}
]
```

It holds no worker count, so it is deterministic for a given input and records stay equal across
worker counts and across CLI/API (existing parity contract).

## Input log (changed, CLI only)

One new line per level, written when that level starts (`InvocationLog.record_write_level`):

```
write_level: 0 shape=(7526, 6985, 6985) chunks=(64, 64, 64) shards=(1024, 1024, 1024) shards_total=392 workers=4 (budget) source=default
```

`workers=N (user)` when `--workers` was given. `--workers` also appears in the existing
`arguments:` block.

## Write lifecycle

```
write_mask(output, mask, run_level, reader, run_record, overwrite, *, workers, progress, on_level)
  validate workers (≥ 1 or None)                         # before touching the filesystem
  refuse existing output unless overwrite                # unchanged
  layouts = plan_layouts(reader)                         # per level, R1
  Image.new(sharded specs) -> to_zarr(tmp)               # metadata only, R5
  for each level:
      resolve worker count; on_level(...); progress(level start)
      idx_z, idx_y, idx_x = physical NN index vectors for this level   # R2, once per level
      thread pool over shard regions:
          skip if the source region is all background (R4)
          block = mask[np.ix_(idx_z[rz], idx_y[ry], idx_x[rx])]         # R2
          z[region] = block
          progress at each 10% of shards                 # R7
  write run_record.json (+ output_layout)
  rename tmp -> output                                   # unchanged atomicity; tmp removed on error
```
