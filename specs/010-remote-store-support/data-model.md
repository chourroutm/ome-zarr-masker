# Data Model: Remote OME-Zarr Store Support

## StoreLocation (new, `src/ome_zarr_masker/io/location.py`)

Parsed form of every input/output argument. Immutable.

| Field | Type | Meaning |
|-------|------|---------|
| `raw` | str | The string the user gave (local path or URL). |
| `kind` | `"local" \| "http" \| "s3" \| "gcs" \| "azure"` | Provider (research R2). |
| `path` | `Path \| None` | Local path (`kind == "local"` only). |
| `bucket` | `str \| None` | S3/GCS bucket or Azure container. |
| `key` | str | Object prefix of the store inside the bucket/container (no leading `/`); for HTTP, the URL path. |
| `host` | `str \| None` | HTTP(S) host (generic HTTP only). |
| `region` | `str \| None` | S3 region taken from an HTTPS host, if present. |
| `account` | `str \| None` | Azure storage account (from URL or ambient config). |

Derived:

- `is_remote` — `kind != "local"`.
- `writable` — `kind in {"local", "s3", "gcs", "azure"}`; generic HTTP is read-only (FR-003).
- `display` — canonical form used in records, logs and errors: the local path as given, or
  `s3://bucket/key`, `gs://bucket/key`, `az://container/key` (plus `account` as
  `az://container/key (account <name>)`), or the HTTP(S) URL.
- `same_store(other)` — equal canonical identity (`kind`, `bucket`, `key` without trailing `/`,
  `account`/`host`; resolved absolute path for local).

Validation rules (raise `RemoteStoreError`):

- `<scheme>://` with a scheme outside `http, https, s3, gs, az, abfs` → `unsupported`.
- URL with userinfo or a query string → `credentials_in_url` (message omits the secret part).
- `az://` with no account in the URL and none in ambient configuration → `unsupported` with a hint.
- Empty bucket/container → `unsupported`.

Operations:

- `open_store(read_only: bool) -> StoreLike` — `str` path for local (unchanged behaviour), an
  `FsspecStore` for remote (research R1, R4). `read_only=False` on a non-writable location →
  `not_writable`.

## RemoteStoreError (new)

`ValueError` subclass with `cause ∈ {not_found, forbidden, network, unsupported, not_writable,
missing_dependency, credentials_in_url}` and `location: str` (the `display` form). Distinct from
`ValidationError` (invalid OME-Zarr) and `WriterError` (output rules).

## Changes to existing records

- **Run record** (`run_record.json`, docs/run-record.md): `input` holds `StoreLocation.display`
  (unchanged for local paths). No new fields. Credentials cannot appear (rejected at parse time).
- **Input log** (feature 002): input/output arguments are logged as given, except that URL
  credentials, query strings and fragments are removed (`redact_url`): the log is written before a
  credential-bearing URL is rejected, so it would otherwise record it (FR-011).

## Write lifecycle of a remote output (research R5)

```text
absent ──write──▶ metadata written, root zarr.json withheld ──levels + run_record──▶ root zarr.json put ──▶ complete
   ▲                         │ failure                                                   
   └──── best-effort delete ◀┘  (never readable as OME-Zarr: no root zarr.json)
existing ──overwrite──▶ root zarr.json deleted ──prefix deleted──▶ absent
```
