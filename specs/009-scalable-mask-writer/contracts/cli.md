# Contract: CLI changes

**Feature**: 009-scalable-mask-writer | **Date**: 2026-10-16

Extends `specs/001-ome-zarr-sam-masking/contracts/cli.md` (`ome-zarr-masker mask`).

## New option

| Arg | Required | Default | Description |
|-----|----------|---------|-------------|
| `--workers INT` | no | automatic (fits an 8 GiB write budget, ≤ CPU count) | Number of output shards written in parallel. Overrides the automatic choice; peak write memory then grows with this number (FR-011). Must be ≥ 1. |

No other new options: there are deliberately no chunk or shard size options (clarification Q2).

## Behavioural contract (testable)

- C-W-CLI-1: `mask` without `--workers` runs exactly as before, and its output follows
  `contracts/output-store.md`.
- C-W-CLI-2: `mask --workers 2` succeeds, and its output store and `run_record.json` are identical
  to a run without `--workers` (except `run_id`).
- C-W-CLI-3: `mask --workers 0` (or a negative number) exits non-zero with a clear message before
  segmentation, and leaves no OUTPUT behind.
- C-W-CLI-4: with `--verbose`, stderr shows one line per output level when it starts (level, shape,
  shard count, worker count) and progress about every 10% of that level's shards. Nothing is added
  to stdout (still only the output path).
- C-W-CLI-5: the input log has one `write_level:` line per output level, with the effective worker
  count and whether it was user-set or budget-derived.
