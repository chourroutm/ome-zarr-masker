# Contract: Python API changes

**Feature**: 009-scalable-mask-writer | **Date**: 2026-10-16

Extends `specs/001-ome-zarr-sam-masking/contracts/python-api.md`.

## `MaskResult.save`

```python
MaskResult.save(
    store_path,
    overwrite: bool = False,
    *,
    workers: int | None = None,                 # NEW: shards written in parallel; None = automatic
    progress: Callable[[str], None] | None = None,  # NEW: write progress messages
) -> Path
```

- Existing calls `save(path)` / `save(path, overwrite=True)` behave as before, apart from the new
  output layout (`contracts/output-store.md`).
- `workers` follows the same rules as CLI `--workers`; values < 1 raise `WriterError` before any
  output is created.
- `progress` receives the same per-level and ~10% messages as the CLI's `--verbose` stream,
  including the effective worker count per level. For API saves this is the only place that count
  is reported (no invocation log is open during `save`, spec FR-012).

`OrganMaskPredictor.predict(...)` and `InteractiveSession.export(...)` are unchanged; export uses the
automatic worker count.

## Behavioural contract (testable)

- C-W-API-1: `save(path, workers=1)` and `save(path, workers=4)` produce identical stores and
  identical `run_record.json` contents.
- C-W-API-2: `save(path, workers=0)` raises `WriterError` and `path` does not exist afterwards.
- C-W-API-3: a `progress` callback gets at least one message per output level and at most
  10 + 1 messages per level.
- C-W-API-4: API and CLI outputs for identical inputs and prompts stay equivalent (existing
  C-API-6), including the new `output_layout` record key.
