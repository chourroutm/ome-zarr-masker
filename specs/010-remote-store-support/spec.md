# Feature Specification: Remote OME-Zarr Store Support

**Feature Branch**: `010-remote-store-support`

**Created**: 2026-10-22

**Status**: Draft

**Input**: User description: "Remote OME-Zarr store support (feature 010). Allow input and output OME-Zarr v0.5 stores to be remote (e.g. HTTP(S) and S3 URLs) rather than only local filesystem paths. The `interactive` subcommand (napari session) only needs read support for remote input stores. The `mask` subcommand needs read support for remote input stores, and write support when the output is a remote store. The Python API should follow the same rules as the CLI (read remote inputs; write to a remote output when saving the mask). Local paths must keep working exactly as today."

## Clarifications

### Session 2026-10-22

- Q: Which object stores besides S3 must be supported? → A: Google Cloud Storage and Azure Blob
  Storage, for both reading and writing, wherever S3 is supported.
- Q: Which URL forms should be accepted for Azure Blob Storage? → A: The scheme-style forms
  (`az://container/path`, `abfs://container@account.dfs.core.windows.net/path`) plus
  `https://<account>.blob.core.windows.net/...` links, which are recognised as Azure (readable and
  writable) rather than treated as generic read-only HTTPS.
- Q: Should HTTPS links that point at S3 or Google Cloud Storage also be recognised as their object
  store? → A: Yes: known S3 hosts (`<bucket>.s3.amazonaws.com`, `<bucket>.s3.<region>.amazonaws.com`,
  `s3.<region>.amazonaws.com/<bucket>`) and `storage.googleapis.com/<bucket>` are treated as S3 and
  Google Cloud Storage, readable and writable with the user's credentials, like Azure links.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Mask a remote input without downloading it first (Priority: P1)

A researcher wants to mask a volume published in a public archive (for example a DANDI dataset
hosted on S3 or served over HTTPS). Today they must first copy the whole OME-Zarr store to local
disk, which for full-resolution HiP-CT volumes is slow and can exceed their quota. With this feature
they pass the store's URL directly as the `mask` input, and the tool reads only the pyramid level it
needs, writing the mask to a local output path as before.

**Why this priority**: Reading remote inputs is the core value: it removes the download step for
every run and is a prerequisite for the other stories.

**Independent Test**: Run `mask` with a remote input URL and a local output path, and compare the
result with the same run on a local copy of that store: the masks are identical.

**Acceptance Scenarios**:

1. **Given** a valid OME-Zarr v0.5 store reachable at an HTTP(S) URL, **When** the user runs `mask`
   with that URL as input and a local output path, **Then** the mask is written locally and is
   identical to the mask produced from a local copy of the same store with the same options.
2. **Given** a valid OME-Zarr v0.5 store in a public S3, Google Cloud Storage or Azure Blob Storage
   bucket or container, **When** the user runs `mask` with its URL, **Then** it succeeds without the
   user configuring any credentials.
3. **Given** a remote store in a private bucket or container on any of these object stores and
   credentials available through the user's standard configuration for that provider, **When** the
   user runs `mask`, **Then** it succeeds using those credentials.
4. **Given** a remote input, **When** the run completes, **Then** the run record and input log record
   the input as the URL the user gave (with no credentials or signed query parameters in it).
5. **Given** a remote input whose metadata is not valid OME-Zarr v0.5, **When** the user runs `mask`,
   **Then** it fails with the same validation error a local store would produce, before any
   segmentation starts.

---

### User Story 2 - Prompt interactively on a remote input (Priority: P2)

A user opens the interactive napari session directly on a remote store URL to place prompts, preview
the mask and save the prompt file, without downloading the store.

**Why this priority**: Prompt authoring usually precedes a masking run; being able to do it on the
same remote store completes the remote workflow. It only needs reading.

**Independent Test**: Launch `interactive` (or construct an interactive session through the Python
API) on a remote URL, add prompts and run a preview: the preview matches the one for a local copy.

**Acceptance Scenarios**:

1. **Given** a remote input URL, **When** the user runs `interactive` with it, **Then** the session
   opens on the selected level and previews behave exactly as for a local store.
2. **Given** an interactive session on a remote input, **When** the user saves prompts, **Then** the
   prompt file is written locally and can be reused by `mask` on the same remote URL or a local copy.
3. **Given** an interactive session on a remote input, **When** the user exports the mask to a remote
   output location, **Then** the export is refused with a clear message that remote output is only
   supported by `mask` and the Python API's mask saving; exporting to a local path works.

---

### User Story 3 - Write the mask to a remote store (Priority: P3)

A user running on a cloud machine or pipeline wants the mask written next to the input in object
storage (S3, Google Cloud Storage or Azure Blob Storage) rather than to local disk. They pass a remote
URL as the `mask` output (or to the Python API's save), and the mask is written there in the same
layout as a local output.

**Why this priority**: Valuable for cloud pipelines but not required to use remote inputs; local
output remains the common case.

**Independent Test**: For each supported object store, run `mask` with an output URL on a test
bucket or container, then read the output back: it is valid OME-Zarr v0.5 and identical (data,
metadata and run record) to a local output of the same run.

**Acceptance Scenarios**:

1. **Given** a writable S3, Google Cloud Storage or Azure Blob Storage location, **When** the user runs
   `mask` with it as output, **Then** the mask pyramid and run record are written there and the output
   is valid OME-Zarr v0.5.
2. **Given** a remote output location that already contains a store, **When** the user runs `mask`
   without `--overwrite`, **Then** it fails before computing anything, as it does for a local output;
   with `--overwrite`, the existing store is replaced.
3. **Given** a remote output, **When** the write fails partway (network loss, permission denied,
   interruption), **Then** the location is not left holding something that reads as a complete,
   valid mask, and the error says what failed.
4. **Given** an output URL that cannot be written to (an HTTP(S) URL on a host that is not S3, Google
   Cloud Storage or Azure Blob Storage), **When** the user runs `mask`, **Then** it fails before
   computing anything with a message naming the supported writable forms.
5. **Given** the Python API, **When** a user saves a mask result to a remote URL, **Then** the same
   rules as the CLI apply.

---

### Edge Cases

- The remote input is unreachable, does not exist, or access is denied: the tool fails before
  segmentation with a message that names the URL and the cause (not found, forbidden, network
  error), distinct from an "invalid OME-Zarr" error.
- The network drops during reading: the run fails with a clear error and writes no output; it does
  not produce a partial mask.
- A local path that happens to contain `:` or looks URL-like (e.g. `./s3:data/x.ome.zarr`) is still
  treated as a local path; only recognised URL schemes are treated as remote.
- An unsupported scheme (e.g. `ftp://`) is rejected with a message listing supported schemes.
- Credentials embedded in a URL or signed query strings never appear in logs, run records or
  error messages.
- A remote input and a remote output that point to the same store (in any of their URL forms) are
  rejected before any computation. Local paths keep today's behaviour, which has no such check.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a remote URL wherever an input OME-Zarr store is accepted: the `mask`
  and `interactive` subcommands and the Python API entry points that open an input store.
- **FR-002**: System MUST support reading remote stores over HTTP(S) and from the object stores, each
  accepted in a scheme form and as an HTTPS link on the provider's own hosts:
  - S3: `s3://bucket/key`, `https://<bucket>.s3[.<region>].amazonaws.com/key`,
    `https://s3.<region>.amazonaws.com/<bucket>/key`;
  - Google Cloud Storage: `gs://bucket/key`, `https://storage.googleapis.com/<bucket>/key`;
  - Azure Blob Storage: `az://container/path`, `abfs://container@account.dfs.core.windows.net/path`,
    `https://<account>.blob.core.windows.net/container/path`.

  HTTPS links on these hosts MUST be opened as the object store (with the user's credentials,
  FR-005), not as generic HTTPS.
- **FR-003**: System MUST support writing the `mask` output, and the Python API's mask save, to S3,
  Google Cloud Storage and Azure Blob Storage, in any of the URL forms of FR-002. HTTP(S) outputs on
  any other host MUST be rejected before any computation with a message naming the writable forms.
- **FR-004**: The interactive session MUST support remote inputs for reading only; exporting a mask
  from it to a remote location MUST be refused with a clear message.
- **FR-005**: Object-store access MUST work anonymously for public buckets and containers and MUST use
  the user's standard credential configuration for each provider (environment, profile or config
  file, or the machine's cloud identity) for private ones; no credentials are passed on the command
  line.
- **FR-006**: Remote inputs MUST be validated as OME-Zarr v0.5 with the same rules and error messages
  as local inputs, before segmentation starts.
- **FR-007**: For the same store contents and options, a run on a remote input MUST produce a mask
  identical to the run on a local copy, and a remote output MUST be identical to a local output
  (data, metadata, layout and run record apart from the recorded input/output locations).
- **FR-008**: System MUST read only the data it needs from a remote input (the metadata and the
  selected level), not the whole store.
- **FR-009**: Remote output MUST follow the local output rules: refuse to replace an existing store
  without overwrite, replace it with overwrite, and never leave a partially written store that reads
  as a complete mask after a failure.
- **FR-010**: Errors for unreachable, missing or forbidden remote locations MUST name the location and
  the cause, and MUST be distinguishable from OME-Zarr validation errors.
- **FR-011**: Run records and input logs MUST record remote locations as URLs with any credentials or
  signed query parameters removed.
- **FR-012**: Local paths MUST behave exactly as today: same accepted forms, outputs, records and
  errors. Only strings with a recognised URL scheme are treated as remote.

### Key Entities

- **Store location**: Where an OME-Zarr store lives: a local path or a remote URL (scheme, bucket or
  host, key). Determines whether the store can be read, written, or both.
- **Remote credentials**: Ambient, provider-specific access configuration for private object storage
  (S3, Google Cloud Storage, Azure Blob Storage); used to open a store but never recorded.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A `mask` run on a remote input produces a mask byte-identical in data to the same run
  on a local copy, in 100% of the test cases.
- **SC-002**: Masking a remote input at a level that is a small fraction of the store transfers no
  more than that level's data plus metadata (within 10%), rather than the whole store.
- **SC-003**: A user can mask a public remote dataset with a single command and no prior download or
  credential setup.
- **SC-004**: Every existing local-path test passes unchanged.
- **SC-005**: After an interrupted remote write, no reader treats the output location as a valid
  complete mask, in 100% of the failure-injection tests.

## Assumptions

- Supported remote locations are HTTP(S) (read-only, apart from links on S3, Google Cloud Storage or
  Azure Blob Storage hosts) and the object stores S3 (including
  S3-compatible endpoints selected through the standard endpoint configuration), Google Cloud Storage
  and Azure Blob Storage (read and write). Other protocols (e.g. FTP, SSH) are out of scope.
- Private-store access relies on the user's existing cloud configuration; the tool adds no
  credential flags or prompts.
- Prompt files, input logs and model weights stay local; only OME-Zarr stores can be remote.
- Remote reads may be slower than local ones; the existing performance budgets apply to local stores,
  and remote runs are measured by data transferred rather than wall time.
- Network access to the remote location is available from the machine running the tool.
