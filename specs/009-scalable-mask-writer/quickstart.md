# Quickstart: Validate the Scalable Mask Writer

Prerequisites: repo checked out, `uv sync` (or `pip install -e ".[dev,sam2]"`). Steps 1–4 need no
GPU or SAM2: they call `write_mask` directly with a synthetic mask. Step 5 runs the CLI end to end.

## 1. Correct voxels, now sharded and compressed (FR-006, C-OUT-2/4)

- **Translation-free input**: build a 3-level input with `tests/conftest.py::write_ome_zarr` (exact
  ×2 ratios, no translations), make a run-level mask at level 1, and write it. Every output level
  equals both the brute-force physical oracle and the old `_nn_resize` copy kept in
  `tests/unit/test_writer.py`, so nothing changes for such inputs.
- **DANDI-style input**: build a small pyramid with half-pixel translations
  `(scale_N − scale_0)/2` and non-exact ratios (e.g. level shapes 941 → 1882/1747 scaled down).
  Every output level equals the brute-force physical oracle, and it differs from the old top-left
  mapping on the finer levels, as expected.
- Open `0/zarr.json`: first codec `sharding_indexed`; inner codecs include `blosc` / `zstd` /
  `bitshuffle`.

Validates C-OUT-2, C-OUT-4.

## 2. Layout copy vs default (FR-007, C-OUT-3)

- Input written with explicit shards (e.g. chunks 16³, shards 32³) → output level has the same
  `chunks`/`shards`; `run_record.json` → `output_layout[i].source == "input"`.
- Input written unsharded (the project's existing fixtures) → output chunks `(64,64,64)`, shards
  rounded up to a multiple of 64 and capped at the level; `source == "default"`.

## 3. Empty shards and disk size (FR-005, SC-002, C-OUT-5)

- All-zero mask → each level directory contains only `zarr.json`.
- Mostly-background mask on a 256³-ish level → total store bytes < 5% of the uncompressed bytes.

## 4. Bounded memory and worker control (FR-002, FR-011, SC-001, SC-006)

```sh
pytest tests/performance/test_writer_perf.py -q
pytest tests/unit/test_writer_layout.py -q
```

Expected:
- writing a 32³ run-level mask into a 512³ finest level under an 8 MiB test budget peaks at < 25% of
  that level's size (tracemalloc);
- `workers=0` raises `WriterError` and creates nothing;
- concurrency never exceeds `workers`;
- writing takes ≤ 1.25× the legacy single-chunk writer timed in the same run;
- a mid-write failure leaves neither the output nor `<output>.tmp`, and an existing output survives a
  failed overwrite.

## 5. CLI end to end (C-W-CLI-1..5)

```sh
ome-zarr-masker mask in.ome.zarr out.ome.zarr --prompts p.json --level 1 --verbose
ome-zarr-masker mask in.ome.zarr out2.ome.zarr --prompts p.json --level 1 --workers 2
ome-zarr-masker mask in.ome.zarr out3.ome.zarr --prompts p.json --level 1 --workers 0; echo $?
```

Expected:
- the first run prints per-level/~10% write progress on stderr; stdout is only the output path;
- `out` and `out2` hold identical voxels, and their `run_record.json` match except `run_id`;
- the third run is rejected as a usage error (exit 2, message names `--workers`) and `out3.ome.zarr`
  doesn't exist;
- each run's input log has one `write_level:` line per level (`workers=2 (user)` for the second).
