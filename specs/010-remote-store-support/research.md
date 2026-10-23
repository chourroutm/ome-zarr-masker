# Research: Remote OME-Zarr Store Support

Feature: `specs/010-remote-store-support/spec.md`. Probed against the project venv: zarr 3.3.0,
ome-zarr-models 1.7, fsspec 2026.7.0 (installed transitively; no provider package installed).

## R1. How remote stores are opened

- **Decision**: Open every remote store as a `zarr.storage.FsspecStore` built from an explicit
  fsspec filesystem (`s3fs.S3FileSystem`, `gcsfs.GCSFileSystem`, `adlfs.AzureBlobFileSystem`,
  `fsspec.implementations.http.HTTPFileSystem`), all with `asynchronous=True`, and pass that store
  object (not a string) to `zarr.open_group` / `zarr.open_array` and to
  `ome_zarr_models.open_ome_zarr` (which accepts any `StoreLike`). Local paths keep the current
  string/`LocalStore` path untouched.
- **Rationale**: zarr 3's `FsspecStore` is the supported remote store; building the filesystem
  ourselves (instead of `FsspecStore.from_url`) lets one parser own URL normalisation (R2), the
  credential policy (R4) and the writable check, and gives a single place to map provider errors
  (R6). Reading through zarr fetches only the metadata documents and the chunks/shards of the level
  being read (FR-008).
- **Alternatives considered**: `obstore`/`ObjectStore` (zarr's Rust-backed store): faster, but a
  newer dependency with less mature Azure/HTTP coverage in our pinned versions, and a second error
  model; can be revisited behind the same `StoreLocation` interface. Downloading to a temp dir:
  violates FR-008 and the quota motivation of US1.

## R2. URL forms and normalisation

- **Decision**: A string is remote only if it starts with `<scheme>://`. Recognised schemes:
  `http`, `https`, `s3`, `gs`, `az`, `abfs`. Any other `<scheme>://` is rejected (unsupported
  scheme, listing the supported ones); anything else is a local path, exactly as today (FR-012).
  HTTPS links are classified by host before falling back to generic HTTP:
  - `<bucket>.s3.amazonaws.com`, `<bucket>.s3.<region>.amazonaws.com`, `s3.<region>.amazonaws.com/<bucket>`,
    `s3.amazonaws.com/<bucket>` → S3 (`bucket`, `key`, optional `region`);
  - `storage.googleapis.com/<bucket>` → GCS;
  - `<account>.blob.core.windows.net/<container>` → Azure (`account`, `container`);
  - `abfs://<container>@<account>.dfs.core.windows.net/<path>` → Azure; `az://<container>/<path>`
    → Azure with the account from standard Azure configuration (`AZURE_STORAGE_ACCOUNT_NAME` or a
    connection string).
  Every location is normalised to a canonical `provider, bucket/container, key, account/region`
  and displayed as the canonical scheme URL (`s3://…`, `gs://…`, `az://…`) next to the URL the user
  gave.
- **Rationale**: Implements spec Clarifications Q1–Q2 with one table-driven parser that is cheap
  to unit-test exhaustively; canonical form makes "same store for input and output" detectable
  regardless of which form each side used.
- **Alternatives considered**: Delegating to `fsspec.url_to_fs`: it treats all `https://` as
  generic HTTP (no provider host recognition) and silently accepts many schemes we don't support.

## R3. Optional dependencies

- **Decision**: New extras `s3 = ["fsspec", "s3fs"]`, `gcs = ["fsspec", "gcsfs"]`,
  `azure = ["fsspec", "adlfs"]`, `http = ["fsspec", "aiohttp"]`, and `remote` = all four. Provider
  modules are imported lazily only when a URL of that provider is opened; a missing package raises
  `RemoteStoreError` naming the extra to install (`pip install "ome-zarr-masker[s3]"`). The core
  install and every local-path run import none of them.
- **Rationale**: gcsfs/adlfs pull large dependency trees (google-auth, azure-identity); local users
  shouldn't pay for them, and the local code path stays byte-for-byte as today (FR-012, SC-004).
- **Alternatives considered**: Hard dependency on all providers (heavy install for local users);
  a single `remote` extra only (forces Azure deps on S3-only users).

## R4. Credentials

- **Decision**: Ambient credentials only (FR-005):
  - S3: s3fs/botocore default chain (env vars, `AWS_PROFILE`/config files, instance role,
    `AWS_ENDPOINT_URL` for S3-compatible endpoints); if botocore resolves **no** credentials, open
    with `anon=True` so public buckets work with no setup.
  - GCS: gcsfs `token=None` (tries Application Default Credentials, then anonymous).
  - Azure: adlfs with `account_name` from the URL (or `AZURE_STORAGE_ACCOUNT_NAME`); credentials
    from `AZURE_STORAGE_CONNECTION_STRING` / `AZURE_STORAGE_SAS_TOKEN` / `AZURE_STORAGE_ACCOUNT_KEY`
    or `DefaultAzureCredential`; anonymous when none is configured.
  - HTTP(S): anonymous GET only.
  URLs carrying userinfo (`user:pass@`) or a query string (`?sig=…`, SAS tokens, presigned
  parameters) are **rejected** with a message that does not echo the URL's secret part and points
  to the provider's ambient configuration.
- **Rationale**: Rejecting embedded secrets makes FR-011 hold by construction (nothing secret can
  reach the run record, input log or error text), and keeps the "no credentials on the command
  line" rule. A store is a prefix of many objects, so a per-object presigned query string couldn't
  open it anyway.
- **Deferred clarify item resolved**: with credentials present, public buckets are read with them
  (public-read grants apply to authenticated principals too); no anonymous retry is attempted, so
  an access error is reported as-is rather than masked by a second attempt.
- **Alternatives considered**: Stripping secrets for records but using them for access (still puts
  credentials on the command line and in shell history); `--anon` / `--profile` flags (FR-005 says
  no credential flags; can be added later without breaking this design).

## R5. Remote write protocol (FR-009)

- **Decision**: Local outputs keep the existing temp-dir-then-rename. Remote outputs, which have no
  atomic rename, use **commit-last**: (1) refuse if the output's root `zarr.json` exists and
  overwrite is off; (2) with overwrite, delete the existing root `zarr.json` first, then the rest of
  the prefix; (3) write the OME metadata with `Image.to_zarr`, then immediately delete the root
  `zarr.json` it wrote, keeping its bytes; (4) write all levels and `run_record.json`; (5) put the
  root `zarr.json` back last. On any failure, best-effort delete of the prefix; if that also fails,
  the prefix still has no root `zarr.json`, so no OME-Zarr reader (nor our validator) accepts it
  as a store.
- **Rationale**: Object stores give per-object atomic puts; the root group document is the one
  object every reader needs first, so its presence is the commit marker. No data copying (a
  staging prefix + server-side copy would double request count and, on Azure/HTTP, isn't
  server-side everywhere).
- **Known difference from local**: on a failed remote overwrite the previous store is already
  gone (locally it survives until the new one is complete). Documented in the CLI contract; it
  still satisfies FR-009's "never leaves something that reads as a complete mask".
- **Alternatives considered**: Staging prefix + copy (cost, above); versioned buckets (not
  portable).

## R6. Error model

- **Decision**: New `RemoteStoreError(ValueError)` in `io/location.py`, with a `cause` of
  `not_found`, `forbidden`, `network`, `unsupported`, `not_writable`, `missing_dependency` or
  `credentials_in_url`. Provider exceptions are mapped once in the location layer:
  `FileNotFoundError` → not_found; `PermissionError` / HTTP 401/403 / botocore `AccessDenied`
  → forbidden; `aiohttp.ClientError`, `OSError`, timeouts → network. Messages name the location as
  displayed (R2) and the cause. `ValidationError` (invalid OME-Zarr) stays distinct (FR-010). CLI
  exit code 1, as for every existing input/output error.
- **Rationale**: Users must be able to tell "can't reach it" from "it isn't v0.5" (FR-010); one
  mapping point keeps reader, validator and writer free of provider specifics.

## R7. Testing without cloud accounts

- **Decision**:
  - URL parsing and classification: exhaustive unit tests (`tests/unit/test_location.py`), no
    network.
  - Generic remote read/write path: fsspec `memory://` filesystem injected through a test-only
    provider hook, plus failure injection (a wrapper filesystem that raises after N puts) for
    FR-009/SC-005.
  - HTTP(S) read: a local `http.server` thread serving a fixture store (also counts bytes served
    for SC-002).
  - S3 read/write: `moto`'s `ThreadedMotoServer` (pure Python, in-process; no Docker), added to the
    `dev` extra.
  - GCS and Azure: classification and filesystem construction (account/container/credential
    options) unit-tested with the filesystem class monkeypatched; real I/O covered by opt-in
    `remote_live` tests that run only when `OME_ZARR_MASKER_TEST_{S3,GCS,AZURE}_URL` point to
    writable test locations. Emulators (fake-gcs-server, Azurite) need Docker/Node, unavailable on
    the target HPC.
- **Rationale**: Deterministic, offline default suite (constitution II) while exercising every
  provider's distinct code (classification + options) and the shared I/O path end-to-end.

## R8. Performance targets

- **Decision**: Local-path runs must not regress (existing budgets and perf tests unchanged; the
  local branch of reader/writer is untouched). Remote read: bytes fetched for a run at level L ≤
  (stored size of level L + metadata documents) × 1.10 (SC-002), measured by the byte-counting
  HTTP server. Remote write: one put per non-empty shard plus metadata (empty shards still skipped,
  feature 009). No wall-clock target for remote runs (network-bound; spec Assumptions).
