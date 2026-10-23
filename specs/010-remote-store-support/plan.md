# Implementation Plan: Remote OME-Zarr Store Support

**Branch**: `010-remote-store-support` | **Date**: 2026-10-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/010-remote-store-support/spec.md`

## Summary

Every OME-Zarr store argument (CLI `mask`/`interactive`, Python API) may now be a remote URL:
HTTP(S) for reading, and S3, Google Cloud Storage and Azure Blob Storage for reading and writing,
each in its scheme form or as an HTTPS link on the provider's hosts (spec Clarifications). The
approach:

- A new `io/location.py` parses each argument once into a `StoreLocation` (local path, or provider +
  bucket/container + key) and opens it: the current string path for local stores, a zarr
  `FsspecStore` over the provider's fsspec filesystem for remote ones (research R1–R2). Provider
  packages are optional extras imported lazily (R3); credentials are ambient only, and URLs with
  embedded secrets are rejected so nothing secret can be recorded (R4).
- `io/reader.py`, `io/validate.py` and `io/writer.py` take a `StoreLocation` instead of a `Path`.
  Their local branch is unchanged. Remote reads go through zarr, so only metadata and the selected
  level are fetched (FR-008).
- Remote writes use a commit-last protocol: the root `zarr.json` is written last and removed first
  on overwrite, so a failed write never reads as a valid store (R5). Local writes keep
  temp-dir-then-rename.
- Provider errors map to one `RemoteStoreError` with a cause (`not_found`, `forbidden`, `network`,
  ...), kept distinct from validation errors (R6). `InteractiveSession.export` refuses remote
  outputs (FR-004).
- Tests stay offline by default: URL-parser unit tests, a `memory://` filesystem with failure
  injection, a local HTTP server and moto's in-process S3 server. GCS and Azure real I/O runs only
  in opt-in `remote_live` tests (R7).

## Technical Context

**Language/Version**: Python 3.11+ (unchanged).

**Primary Dependencies**: `zarr>=3` (`FsspecStore`; probed on 3.3.0), `ome-zarr-models>=1.6`
(`open_ome_zarr` accepts a store object; 1.7 installed), `numpy` (unchanged). New **optional**
extras (research R3): `s3` (`fsspec`, `s3fs`), `gcs` (`fsspec`, `gcsfs`), `azure` (`fsspec`,
`adlfs`), `http` (`fsspec`, `aiohttp`), `remote` (all four). `dev` gains `moto[server]`.
Local-only installs gain no dependency.

**Storage**: OME-Zarr v0.5 stores on local disk (unchanged) or in remote object storage / over HTTP.
The on-store layout is identical to feature 009's output (`contracts/output-store.md` of 009).

**Testing**: pytest. New `tests/unit/test_location.py` (parsing, classification, credential and
scheme rejection, filesystem options per provider with the filesystem classes monkeypatched),
`tests/integration/test_remote_read.py` (local HTTP server fixture, byte counting),
`tests/integration/test_remote_s3.py` (moto `ThreadedMotoServer`),
`tests/integration/test_remote_write_failures.py` (`memory://` + put-failure injection) and
`tests/integration/test_remote_api.py`. Outputs are checked with
`tests/conftest.py::assert_ome_zarr_models_valid` and compared with local outputs of the same run.
A new marker, `remote_live`, is deselected unless `OME_ZARR_MASKER_TEST_{S3,GCS,AZURE}_URL` is set.
Tests that need SAM2 reuse the existing `real_backend` gating; parsing and write-protocol tests
call `write_mask` directly with synthetic masks.

**Target Platform**: Linux/macOS CLI and Python library (unchanged); network access to the remote
location.

**Project Type**: Single project (library + CLI), layout under `src/ome_zarr_masker/`.

**Performance Goals**:
- Local-path runs: no regression against the existing budgets (feature 009 perf tests and level
  speed test unchanged). The local code path is not modified.
- Remote read: bytes fetched for a run at level L ≤ 1.10 × (stored bytes of level L + metadata
  documents) (SC-002), measured by the byte-counting HTTP fixture.
- Remote write: one put per non-empty shard plus the metadata documents and `run_record.json`;
  empty shards are still skipped (009).
- No wall-clock target for remote runs; they are network-bound (spec Assumptions).

**Constraints**: Peak memory for a remote write is the same as for local (009's 8 GiB shard
budget). The remote read buffers only the selected level (as local does today). Parsing and
rejecting a location costs no network I/O. Errors are raised before segmentation whenever they can
be detected up front (FR-003, FR-006, C-LOC-*).

**Scale/Scope**: Inputs up to full-resolution HiP-CT/DANDI pyramids (a typical run reads a coarse
level of a few GB). Five store-taking entry points (`mask` input and output, `interactive` input,
`set_volume`, `MaskResult.save`), plus the `export` refusal. About 6 source files touched, 1 new.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| I. Code Quality | Lint/format clean; one new module with documented public names (`StoreLocation`, `RemoteStoreError`); no new CLI flags; provider specifics confined to `io/location.py` | PASS |
| II. Test Discipline | Each FR/contract item maps to a failing-first test (quickstart steps 1–5); the default suite stays deterministic and offline (moto, local HTTP server, `memory://`); live clouds are opt-in | PASS |
| III. Version Control | Planned commits: location parser → read path → write path → API/interactive rules → docs; each green | PASS |
| IV. Performance | Targets declared above (SC-002 byte budget; no local regression); measured by the byte-counting HTTP fixture and the existing perf tests | PASS |

Post-design re-check (after Phase 1): PASS. The design adds no new projects or layers. The one
behavioural difference from local output (a failed remote overwrite loses the old store, R5) is
documented in `contracts/cli.md` C-R-CLI-4 and still meets FR-009. No Complexity Tracking entry is
needed.

## Project Structure

### Documentation (this feature)

```text
specs/010-remote-store-support/
├── plan.md              # This file
├── research.md          # Phase 0: R1–R8
├── data-model.md        # StoreLocation, RemoteStoreError, remote write lifecycle
├── quickstart.md        # Validation scenarios 1–7
├── contracts/
│   ├── store-location.md  # Accepted URL forms, C-LOC-1…8
│   ├── cli.md             # C-R-CLI-1…9
│   └── python-api.md      # C-R-API-1…3
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/ome_zarr_masker/
├── io/
│   ├── location.py      # NEW: StoreLocation.parse, open_store, provider filesystems, RemoteStoreError
│   ├── reader.py        # OmeZarrReader takes a StoreLocation; opens group/arrays via open_store
│   ├── validate.py      # validate_ome_zarr works on a StoreLocation (existence + version sniff via store reads)
│   └── writer.py        # write_mask: local branch unchanged; remote commit-last protocol (R5)
├── engine/pipeline.py   # parse locations once; same-store check for remote; record display form
├── api.py               # set_volume / MaskResult.save accept URLs
├── interactive.py       # accepts remote input; export() refuses remote output
└── cli.py               # help text mentions URLs; maps RemoteStoreError to exit 1

tests/
├── unit/test_location.py
├── integration/test_remote_read.py
├── integration/test_remote_s3.py
├── integration/test_remote_write_failures.py
├── integration/test_remote_api.py
└── conftest.py          # http_store_server, moto_s3, memory_fs fixtures; remote_live marker

pyproject.toml           # extras s3/gcs/azure/http/remote; dev += moto[server]; remote_live marker
README.md, docs/run-record.md   # remote usage, credentials, extras, overwrite caveat
```

**Structure Decision**: Single project, as before. The only new module is `io/location.py`, next
to the reader, validator and writer that use it, and it keeps all provider-specific code in one
place.

## Complexity Tracking

No constitution violations; nothing to justify.
