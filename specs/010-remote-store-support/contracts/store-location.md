# Contract: Store locations (input and output arguments)

**Feature**: 010-remote-store-support | **Date**: 2026-10-22

Applies to every argument that names an OME-Zarr store: `mask INPUT OUTPUT`, `interactive INPUT`,
`OrganMaskPredictor.set_volume(store_path)`, `MaskResult.save(store_path)`,
`InteractiveSession(store_path)` / `.export(output_path)`. Data model: `data-model.md`.

## Accepted forms

| Form | Provider | Read | Write |
|------|----------|------|-------|
| any string without `<scheme>://` | local path (unchanged) | yes | yes |
| `s3://bucket/key` | S3 | yes | yes |
| `https://bucket.s3.amazonaws.com/key`, `https://bucket.s3.<region>.amazonaws.com/key` | S3 | yes | yes |
| `https://s3.<region>.amazonaws.com/bucket/key`, `https://s3.amazonaws.com/bucket/key` | S3 | yes | yes |
| `gs://bucket/key`, `https://storage.googleapis.com/bucket/key` | Google Cloud Storage | yes | yes |
| `az://container/path` (account from `AZURE_STORAGE_ACCOUNT_NAME` or connection string) | Azure Blob | yes | yes |
| `abfs://container@account.dfs.core.windows.net/path` | Azure Blob | yes | yes |
| `https://account.blob.core.windows.net/container/path` | Azure Blob | yes | yes |
| any other `http://` / `https://` URL | generic HTTP(S) | yes | **no** |

A trailing `/` is ignored. Hosts are matched case-insensitively; bucket/key are case-sensitive.

## Behavioural contract (testable)

- C-LOC-1: Strings without `<scheme>://` are local paths, handled exactly as before (FR-012),
  including relative paths and names containing `:` (e.g. `./s3:data/x.ome.zarr`).
- C-LOC-2: `<scheme>://` with an unsupported scheme (e.g. `ftp://`, `file://`, `gcs://`) fails before
  any work with `RemoteStoreError(cause="unsupported")` listing the supported forms.
- C-LOC-3: A URL with userinfo or a query string fails before any work with
  `RemoteStoreError(cause="credentials_in_url")`; the message does not contain the userinfo or
  query text.
- C-LOC-4: Each HTTPS form in the table resolves to the same location as its scheme form (e.g.
  `https://b.s3.us-east-1.amazonaws.com/k` ≡ `s3://b/k` with region `us-east-1`).
- C-LOC-5: An output that is generic HTTP(S) fails before any computation with
  `RemoteStoreError(cause="not_writable")` naming the writable forms.
- C-LOC-6: Opening a location whose provider package is not installed fails with
  `RemoteStoreError(cause="missing_dependency")` naming the extra (`ome-zarr-masker[s3]`, `[gcs]`,
  `[azure]`, `[http]`, or `[remote]` for all).
- C-LOC-7: Unreachable / missing / forbidden locations fail with causes `network` / `not_found` /
  `forbidden`, a message naming the location's display form, and are never reported as an
  OME-Zarr validation error (FR-010).
- C-LOC-8: Credentials come only from the provider's ambient configuration; with none configured,
  access is anonymous (FR-005, research R4).
