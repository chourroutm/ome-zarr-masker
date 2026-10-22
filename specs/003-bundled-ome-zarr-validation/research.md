# Phase 0 Research: Bundled OME-Zarr Validation Dependency

**Feature**: 003-bundled-ome-zarr-validation | **Date**: 2026-06-23

## Decision 1 — Validate in-process via `ome_zarr_models.open_ome_zarr`

**Decision**: Replace the `subprocess` call to the `ome-zarr-models validate` console script with an
in-process call to `ome_zarr_models.open_ome_zarr(store, version="0.5")`, wrapped so that
`ome_zarr_models.exceptions.ValidationWarning` is escalated to an error
(`warnings.catch_warnings(action="error", category=ValidationWarning)`).

**Rationale**:
- `open_ome_zarr` is the documented top-level public API of `ome-zarr-models`. It opens the group
  and validates the metadata against the OME-Zarr group models, raising `RuntimeError` (and related
  exceptions) when the data cannot be validated. This is exactly the gate the feature needs, with no
  external process and therefore no `PATH` dependency (FR-001, FR-002, SC-003).
- It mirrors the package's own CLI: `ome_zarr_models._cli.validate()` calls
  `open_ome_zarr(path, version=version)` inside a `catch_warnings(action="error",
  category=ValidationWarning)` block. Reusing the identical mechanism preserves current
  validation outcomes (FR-003, FR-004, SC-002) — anything the bundled CLI accepted/rejected, the
  in-process path accepts/rejects the same way, because it runs the same code.
- Removing the sub-process spawn is a strict performance win (no extra interpreter startup),
  satisfying SC-005 with margin.

**Alternatives considered**:
- *Resolve and invoke the console script without `PATH`* (e.g. via `importlib.metadata` entry
  points or `python -m`). Rejected: still spawns a process and keeps subprocess plumbing for no
  benefit; the in-process API is simpler and faster and is the package's intended interface.
- *Use a specific group class directly* (e.g. `ome_zarr_models.v05.Image.from_zarr`). Rejected:
  the input may legitimately be any OME-Zarr v0.5 group type; `open_ome_zarr` performs the same
  "guess the type" validation the CLI does, keeping parity and avoiding over-narrowing.

## Decision 2 — Version pinning of `open_ome_zarr(..., version=...)`

**Decision**: Pass `version="0.5"`.

**Rationale**: ome-zarr-masker is explicitly an OME-Zarr **v0.5** tool — the reader, writer, and
all contracts target v0.5, and the spec states v0.5 remains the only supported input version
(Assumptions). Pinning `version="0.5"` makes validation assert the version the rest of the pipeline
requires, rather than silently accepting a v0.4 store that the downstream reader would then fail on
with a less clear error. The previous subprocess call passed no version (inferred), but a v0.4 store
was never actually usable by this tool, so this is a clarification, not a behavioral regression for
any input that could have produced a successful masking run.

**Alternatives considered**:
- *`version=None` (infer), to byte-match the old subprocess command.* Rejected: it would let a v0.4
  store pass the validation gate only to fail deeper in the pipeline; pinning v0.5 fails fast with a
  clearer message and matches the tool's actual contract. Documented here so the deviation from the
  old command's exact flags is explicit.

## Decision 3 — Error mapping and missing-dependency handling

**Decision**: Keep the public contract identical: `validate_ome_zarr(path) -> None`, raising
`ValidationError` on any problem. Specifically:
- Missing path -> `ValidationError("input store does not exist: <path>")` (unchanged, checked first).
- Validation failure (`open_ome_zarr` raises, or a `ValidationWarning` is escalated) ->
  `ValidationError("input is not a valid OME-Zarr v0.5 store: <message>")`.
- `ome-zarr-models` (or `zarr`) not importable -> `ValidationError` whose message names the missing
  dependency and how to install it (FR-005), raised by catching `ImportError` around the import.

**Rationale**: Downstream callers (reader, pipeline, CLI `_cmd_mask`, API `predict`) already catch
`ValidationError`; preserving the type and the "does not exist" / "not a valid ... store" message
shapes guarantees no caller change and no behavior regression (SC-002). FR-005 is satisfied with an
actionable message rather than a raw `ImportError`/`command not found`.

## Decision 4 — Dependency floor (FR-007)

**Decision**: Keep the declared floor at `ome-zarr-models>=1.6` (already in `pyproject.toml`),
confirming `open_ome_zarr` and `exceptions.ValidationWarning` are part of that public API. Raise the
floor only if verification shows `open_ome_zarr` was introduced after 1.6.

**Rationale**: `open_ome_zarr` is the top-level entry point present in the installed 1.7 and is the
documented public API for v0.5 support, which `ome-zarr-models` has carried since the 1.x line. A
declared minimum (`>=1.6`) gives reproducible validation behavior across installs (FR-007) without
gratuitously excluding currently-working versions. Implementation will confirm the symbol exists at
the declared floor; if not, bump to the first version that exports it in a separate, atomic commit.

**Alternatives considered**:
- *Pin an exact version.* Rejected: over-constrains users and conflicts with normal library
  dependency hygiene; a minimum floor is sufficient for reproducible behavior here.

## Open questions

None. All spec Assumptions are resolved: in-process validation is chosen over a bundled script, no
`PATH` prerequisite remains, and validation outcomes/error semantics are preserved.
