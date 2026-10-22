# Phase 1 Data Model: Bundled OME-Zarr Validation Dependency

**Feature**: 003-bundled-ome-zarr-validation | **Date**: 2026-06-23

This feature changes *how* an existing entity is validated, not its shape. No new persisted data is
introduced. The relevant entities from the spec:

## OME-Zarr v0.5 store (input)

- **What**: The input volume the user wants to mask, on the local filesystem.
- **Validation rule (changed mechanism, same outcome)**: MUST validate as a conformant OME-Zarr
  **v0.5** group before any masking begins. Validation is performed **in-process** by
  `ome_zarr_models.open_ome_zarr(store, version="0.5")` with `ValidationWarning` treated as an
  error. It no longer depends on a validator command being on `PATH`.
- **States**:
  - *Missing* (path does not exist) -> rejected: `ValidationError("input store does not exist: ...")`.
  - *Present but not a valid OME-Zarr v0.5 store* -> rejected:
    `ValidationError("input is not a valid OME-Zarr v0.5 store: <detail>")`.
  - *Valid v0.5 store* -> accepted (function returns `None`); the run proceeds.
- **Invariants**: Outcomes are identical to the prior subprocess-based validation for every input
  that could have produced a successful run (FR-003, FR-004, SC-002). The public contract
  `validate_ome_zarr(path: str | Path) -> None` and the `ValidationError` type are unchanged.

## Validation dependency

- **What**: The OME-Zarr metadata/validation capability ome-zarr-masker relies on, now consumed
  in-process from the installed `ome-zarr-models` package (with `zarr>=3`).
- **Fields / declaration**: Declared in `pyproject.toml` as `ome-zarr-models>=1.6` (a minimum
  compatible floor for reproducible behavior — FR-007). No new dependency added.
- **Validation rule**: If the dependency is unavailable at runtime (broken/partial install), the
  tool MUST raise `ValidationError` whose message names the missing dependency and how to install
  it (FR-005), rather than a raw `ImportError` or "command not found".
- **Relationships**: Used exclusively by `io/validate.py`; all other modules consume validation only
  through `validate_ome_zarr` / `ValidationError`.
