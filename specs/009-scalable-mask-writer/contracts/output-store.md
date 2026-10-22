# Contract: Output store layout

**Feature**: 009-scalable-mask-writer | **Date**: 2026-10-16

What a mask written by `write_mask` (CLI `mask`, API `MaskResult.save`, interactive export) looks
like on disk. See `../data-model.md` for the `LevelLayout` rules.

## Guarantees

- C-OUT-1: Same level count, dataset paths, shapes, axes and coordinate transforms as the input
  (unchanged from feature 001).
- C-OUT-2: Every level is `uint8`, `fill_value=0`, and uses the `sharding_indexed` codec with inner
  codecs `bytes` + `blosc(cname="zstd", clevel=3, shuffle="bitshuffle")`.
- C-OUT-3: Layout: when the matching input level is sharded, the output level's `chunks` and
  `shards` equal the input level's. Otherwise `chunks=(64,64,64)` and
  `shards[a] = min(1024, roundup(shape[a], 64))`.
- C-OUT-4: Voxel values at every level equal the physical nearest-neighbour resampling of the
  run-level mask: per axis, `x = (i·scale_dst + trans_dst − trans_src) / scale_src` and
  `idx = clip(ceil(x − 0.5 − 1e-9), 0, src − 1)` (exact ties → lower index; scale 1, translation 0
  when absent). Same as the previous writer for translation-free, exact-ratio inputs.
- C-OUT-5: All-background shards are not stored, so a fully background mask's level directories
  contain only metadata.
- C-OUT-6: `run_record.json` holds all its existing keys plus `output_layout` (one entry per level:
  `level, shape, chunks, shards, compressor, source`). It never holds a worker count.
- C-OUT-7: The store passes `validate_ome_zarr` and opens with `OmeZarrReader`. A single shard can be
  read without reading the rest of its level.
- C-OUT-8: Unchanged safety: an existing output is replaced only with overwrite, and a failed write
  leaves no output and no `.tmp` directory.

## Downstream note

ome-zarr-tools' `apply_mask` works with any of these layouts (research R9). Matching the volume's
layout, which happens automatically for sharded inputs, is the cheapest case for it to read.
