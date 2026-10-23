# Quickstart: Validate Remote Store Support

Prerequisites: repo checked out, `uv sync --all-extras` (installs the new `remote` extra and
`moto` in `dev`). Steps 1–5 are offline and need no cloud account; step 6 is opt-in. Steps 2–5 that
run `mask` end to end need SAM2 (CPU is enough for the tiny fixtures).

## 1. Location parsing (contracts/store-location.md C-LOC-1…6)

`uv run pytest -q tests/unit/test_location.py`: every row of the accepted-forms table resolves to
the expected provider/bucket/key/account; HTTPS forms equal their scheme forms; `ftp://`,
`file://`, URLs with `user:pass@` or `?sig=` are rejected with the right cause and no secret in
the message; local strings (including `./s3:data/x.ome.zarr`) stay local.

## 2. Remote read over HTTP(S) (US1, FR-007, FR-008, SC-001, SC-002)

`uv run pytest -q tests/integration/test_remote_read.py`: a fixture store served by a local HTTP
server is masked with a local output; the output equals the local-input run (C-R-CLI-2), and the
bytes served are ≤ 1.10 × (run level + metadata). Missing path → `not_found`; server stopped →
`network`; both exit 1 and are not validation errors (C-LOC-7). A v0.4 store served remotely gets
the same "requires OME-Zarr v0.5" message as locally (FR-006).

## 3. S3 read and write (US1, US3) with moto

`uv run pytest -q tests/integration/test_remote_s3.py`: with `ThreadedMotoServer` and
`AWS_ENDPOINT_URL` set, mask `s3://in/vol.ome.zarr` → `s3://out/mask.ome.zarr`; the output passes
`assert_ome_zarr_models_valid` and equals a local output (C-R-CLI-3). Re-run without `--overwrite`
fails; with it succeeds (C-R-CLI-4). Same store for input and output fails (C-R-CLI-6). With no
credentials configured, a public bucket is read anonymously (C-LOC-8).

## 4. Failure safety (FR-009, SC-005)

`uv run pytest -q tests/integration/test_remote_write_failures.py`: a filesystem that fails after
N puts (for several N) makes `mask` exit 1; afterwards the output prefix has no root `zarr.json`
and `validate_ome_zarr` rejects it (C-R-CLI-5).

## 5. Interactive and API rules (US2, C-R-API-1…3)

`uv run pytest -q tests/integration/test_remote_api.py`: `InteractiveSession` and
`OrganMaskPredictor.set_volume` read the HTTP fixture; `MaskResult.save` to `s3://` equals CLI
output; `InteractiveSession.export("s3://…")` raises `not_writable` and writes nothing.

## 6. Live clouds (optional)

Set any of `OME_ZARR_MASKER_TEST_S3_URL`, `OME_ZARR_MASKER_TEST_GCS_URL`,
`OME_ZARR_MASKER_TEST_AZURE_URL` to a writable test prefix (ambient credentials for that provider
configured), then `uv run pytest -q -m remote_live`: each provider round-trips a mask and reads it
back identical to a local output.

## 7. Regression

`uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest -q`: every
existing local-path test passes unchanged (SC-004).

## Validation record (2026-10-23)

- Steps 1–5 and 7 on the login node: `uv run pytest -m "not real_backend and not slow"`: 255
  passed, 4 skipped (the 3 opt-in `remote_live` tests and one existing skip); ruff check and
  format clean.
- Slow and `real_backend` tests on a GPU node (`salloc -p mit_normal_gpu --gres=gpu:1`): 48 passed
  after the change, the same as the 48 before it, including the feature 009 writer performance and
  level-speed tests (no local regression, SC-004).
- Step 6 (live clouds) not run: no test buckets configured.
