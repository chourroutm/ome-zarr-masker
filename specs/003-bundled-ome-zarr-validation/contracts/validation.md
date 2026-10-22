# Contract: Input Validation

**Feature**: 003-bundled-ome-zarr-validation

The validation contract is the existing internal interface in
`src/ome_zarr_masker/io/validate.py`. This feature preserves the contract and changes only the
implementation (in-process instead of subprocess). Contract IDs are referenced by the quickstart
and by tasks.

## Interface (unchanged)

```python
def validate_ome_zarr(path: str | Path) -> None: ...
class ValidationError(RuntimeError): ...
```

- `validate_ome_zarr(path)` returns `None` when `path` is a valid OME-Zarr v0.5 store.
- It raises `ValidationError` (only) when validation fails. No other exception type escapes.

## Contract assertions

- **C-VAL-1 (valid passes, no PATH)**: Given a valid OME-Zarr v0.5 store and **no** `ome-zarr-models`
  command anywhere on `PATH`, `validate_ome_zarr` returns `None`. (FR-001, FR-002, SC-003)
- **C-VAL-2 (in-process, no subprocess)**: A successful or failing validation spawns **no** child
  process (no `subprocess` call). (FR-002 — behavior independent of any on-`PATH` command)
- **C-VAL-3 (invalid rejected)**: Given a directory/store that is not a valid OME-Zarr v0.5 group,
  `validate_ome_zarr` raises `ValidationError` with an actionable message containing
  "not a valid OME-Zarr v0.5 store". (FR-004, SC-002)
- **C-VAL-4 (missing path rejected)**: Given a path that does not exist, `validate_ome_zarr` raises
  `ValidationError` whose message says the input store does not exist. (FR-004)
- **C-VAL-5 (missing dependency)**: If `ome-zarr-models` cannot be imported, `validate_ome_zarr`
  raises `ValidationError` whose message names `ome-zarr-models` and how to install it (not a raw
  `ImportError`). (FR-005)
- **C-VAL-6 (no regression)**: Every input accepted/rejected by the prior subprocess-based
  validation is accepted/rejected identically (verified by the existing valid/invalid/missing unit
  tests staying green). (FR-003, SC-002)
- **C-VAL-7 (performance)**: Validation of the synthetic valid store completes well under the prior
  subprocess cost (budget < 500 ms) and spawns no sub-process. (SC-005, Constitution IV)
