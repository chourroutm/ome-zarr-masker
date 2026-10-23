# Contract: Python API changes

**Feature**: 010-remote-store-support | **Date**: 2026-10-22

Extends `specs/001-ome-zarr-sam-masking/contracts/python-api.md`. No signature changes: every
`store_path: str | Path` parameter additionally accepts the URL strings of
`contracts/store-location.md`.

| Entry point | Remote read | Remote write |
|-------------|-------------|--------------|
| `OrganMaskPredictor.set_volume(store_path, level=...)` | yes | — |
| `MaskResult.save(store_path, overwrite=False, *, workers=None)` | — | yes (writable forms) |
| `InteractiveSession(store_path, ...)` | yes | — |
| `InteractiveSession.export(output_path, overwrite=False)` | — | **no**: remote `output_path` raises `RemoteStoreError(cause="not_writable")` with a message that remote output is supported by `mask` and `MaskResult.save` |

New public names (importable from `ome_zarr_masker.io.location`):

- `RemoteStoreError(ValueError)` with attributes `cause: str` and `location: str`.
- `StoreLocation.parse(value: str | Path) -> StoreLocation` (see `data-model.md`).

## Behavioural contract (testable)

- C-R-API-1: `MaskResult.save` to a remote URL produces the same store as the CLI `mask` with the
  same inputs and that URL as `OUTPUT` (CLI/API parity, as feature 001 SC-005).
- C-R-API-2: `MaskResult.save` follows C-R-CLI-4/5/6 (overwrite, failure, same-store rules).
- C-R-API-3: `InteractiveSession.export` to a local path is unchanged; to any remote URL it raises
  before computing or writing anything.
