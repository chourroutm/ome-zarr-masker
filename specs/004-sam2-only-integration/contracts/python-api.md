# Python API Contract Delta: SAM2-Only Integration

Supersedes the `backend` clauses of
[specs/001-ome-zarr-sam-masking/contracts/python-api.md](../../001-ome-zarr-sam-masking/contracts/python-api.md).
All other clauses in that document are unchanged by this feature.

## Removed clause

- ~~`OrganMaskPredictor(backend="sam2", model_dir=None, allow_download=True)` — `backend`: `"sam2"`
  (default) or `"sam3"` (FR-018).~~ The `backend` parameter is removed entirely.
- ~~C-API-7: `backend="sam3"` runs the same flow and produces a comparable mask object (SC-010).~~
  Removed — no backend selection exists.

## Changed clause

`OrganMaskPredictor(model_dir=None, allow_download=True, log_dir=None, log_level=None)`

SAM2 is always used; there is no `backend` parameter to pass. `RunConfig` likewise has no `backend`
field.

## New clause

- **C-API-8**: `OrganMaskPredictor(backend="sam3")` (or any `backend=` argument) MUST raise
  `TypeError: __init__() got an unexpected keyword argument 'backend'` at construction time — a
  standard Python parameter-validation error, not application-level logic (FR-004).
