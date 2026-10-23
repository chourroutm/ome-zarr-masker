---

description: "Task list for feature 010: remote OME-Zarr store support"
---

# Tasks: Remote OME-Zarr Store Support

**Input**: Design documents from `/specs/010-remote-store-support/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R8), data-model.md, contracts/ (store-location.md,
cli.md, python-api.md), quickstart.md

**Tests**: Required (Constitution II, Test Discipline). Write each test task first and confirm it
fails before the matching implementation task.

**Organization**: Grouped by user story (US1 P1 remote read for `mask`, US2 P2 remote input for
`interactive`, US3 P3 remote output) so each story can be implemented and tested on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: User story the task belongs to (US1, US2, US3)

## Path Conventions

Single project: package `src/ome_zarr_masker/`, tests under `tests/`. Commands run from the repo
root with `uv run`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Optional dependencies, test marker and install

- [X] T001 Add optional extras to `pyproject.toml` (research R3): `s3 = ["fsspec", "s3fs"]`, `gcs = ["fsspec", "gcsfs"]`, `azure = ["fsspec", "adlfs"]`, `http = ["fsspec", "aiohttp"]`, `remote = ["ome-zarr-masker[s3,gcs,azure,http]"]`; add `moto[server]` to `dev`; register the pytest marker `remote_live: tests against real cloud buckets, run only when OME_ZARR_MASKER_TEST_{S3,GCS,AZURE}_URL is set`
- [X] T002 Run `uv sync --all-extras` and confirm `python -c "import s3fs, gcsfs, adlfs, aiohttp, moto"` succeeds in the venv; then confirm `uv run pytest -q -m "not slow"` passes before any code change (local-path baseline for SC-004)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: `StoreLocation`, `RemoteStoreError` and the shared remote test fixtures that every story uses

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Tests for the foundation (write first, must fail)

- [X] T003 [P] Write `tests/unit/test_location.py` covering contracts/store-location.md C-LOC-1…6 with no network: every row of the accepted-forms table parses to the expected `kind`/`bucket`/`key`/`region`/`account` (including `abfs://c@acct.dfs.core.windows.net/p`, `https://acct.blob.core.windows.net/c/p`, `https://b.s3.us-east-1.amazonaws.com/k`, `https://s3.eu-west-1.amazonaws.com/b/k`, `https://storage.googleapis.com/b/k`); each HTTPS provider form is `same_store` as its scheme form (C-LOC-4); trailing `/` is ignored and hosts match case-insensitively; `display` gives `s3://…`, `gs://…`, `az://… (account <name>)` or the HTTP URL and the local path unchanged; `writable` is false only for generic HTTP(S); local strings stay local (`out.ome.zarr`, `./s3:data/x.ome.zarr`, absolute paths, `Path` objects) (C-LOC-1); `ftp://`, `file://`, `gcs://` raise `RemoteStoreError(cause="unsupported")` listing supported forms (C-LOC-2); `https://u:p@h/x` and `s3://b/k?sig=abc` raise `cause="credentials_in_url"` and the message contains neither `u:p` nor `sig=abc` (C-LOC-3); `az://c/p` with no `AZURE_STORAGE_ACCOUNT_NAME`/connection string raises `unsupported` with a hint; empty bucket raises `unsupported`; `open_store(read_only=False)` on generic HTTP raises `not_writable` (C-LOC-5); a monkeypatched failed import of `s3fs` raises `missing_dependency` naming `ome-zarr-masker[s3]` (C-LOC-6)
- [X] T004 Add to `tests/unit/test_location.py` the per-provider filesystem-option tests (research R4) with the filesystem classes monkeypatched to record their kwargs: S3 uses `anon=True` when botocore resolves no credentials and no `anon` otherwise, and passes the HTTPS-host region; GCS passes `token=None`; Azure passes `account_name` from the URL or `AZURE_STORAGE_ACCOUNT_NAME`; HTTP is anonymous; all filesystems are built with `asynchronous=True`; and the provider-error mapping (R6): `FileNotFoundError` → `not_found`, `PermissionError`/HTTP 403 → `forbidden`, `OSError`/timeout/`aiohttp.ClientError` → `network`, each message naming `display`

### Implementation for the foundation

- [X] T005 Create `src/ome_zarr_masker/io/location.py` (data-model.md): `RemoteStoreError(ValueError)` with `cause` and `location` attributes; frozen dataclass `StoreLocation` with fields `raw, kind, path, bucket, key, host, region, account`, classmethod `parse(value: str | Path)` implementing the table-driven classification of research R2 and the rejection rules (unsupported scheme, credentials in URL without echoing them, `az://` without an account, empty bucket), and properties `is_remote`, `writable`, `display`, plus `same_store(other)` (local: resolved absolute path; remote: kind, bucket, key without trailing `/`, account/host); parsing does no network I/O. `Path` inputs and strings without `<scheme>://` return `kind="local"` with `path=Path(value)`. Make T003 pass for parsing
- [X] T006 Add `StoreLocation.open_store(read_only: bool)` in `src/ome_zarr_masker/io/location.py`: returns `str(self.path)` for local (unchanged behaviour); for remote, lazily imports the provider package (raising `missing_dependency` with the extra name), builds the fsspec filesystem with the options of research R4 (`asynchronous=True`) and wraps it in `zarr.storage.FsspecStore(fs, path=<bucket>/<key>, read_only=read_only)`; raises `not_writable` when `read_only=False` and not `writable`. Add a private test hook (module-level `_FILESYSTEM_OVERRIDE: dict[str, Callable]`) that lets tests supply the filesystem for a kind (used for `memory://` injection, research R7). Add `map_remote_error(exc, location) -> RemoteStoreError` and a context manager `remote_errors(location)` that applies it (R6). Make T003–T004 pass
- [X] T007 Export `StoreLocation` and `RemoteStoreError` from `src/ome_zarr_masker/io/__init__.py` (and keep `ome_zarr_masker.io.location` importable per contracts/python-api.md)
- [X] T008 Add shared fixtures to `tests/conftest.py`: `http_store_server` (a `http.server.ThreadingHTTPServer` thread serving a directory, yielding its base URL and a `bytes_served` counter, stoppable mid-test); `moto_s3` (a `moto.server.ThreadedMotoServer` on a free port with `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` test values and `AWS_DEFAULT_REGION` set via `monkeypatch`, plus a helper to upload a local store directory to a bucket); `memory_fs` (installs a fresh fsspec `MemoryFileSystem` through the `_FILESYSTEM_OVERRIDE` hook for kind `s3` and clears it afterwards); a `FailingFileSystem` wrapper that raises `OSError` after N put/pipe calls; and skip logic so `remote_live` tests skip unless their `OME_ZARR_MASKER_TEST_*_URL` variable is set

**Checkpoint**: `uv run pytest -q tests/unit/test_location.py` passes; existing tests untouched and green

---

## Phase 3: User Story 1 - Mask a remote input without downloading it first (Priority: P1) 🎯 MVP

**Goal**: `mask` (and the pipeline) read an OME-Zarr v0.5 input from HTTP(S), S3, GCS or Azure, fetching only metadata and the selected level, and write a local output identical to a local-input run.

**Independent Test**: quickstart.md steps 2–3 (read half): `mask <url> out.ome.zarr` equals `mask <local copy> out.ome.zarr`.

### Tests for User Story 1 (write first, must fail)

- [X] T009 [P] [US1] Write `tests/integration/test_remote_read.py` (HTTP fixture from T008): validator and `OmeZarrReader` open the served synthetic store and `read_level` equals the local read for every level; the pipeline with a stub/injected segmenter (as existing integration tests do) writes a local output equal to the local-input run, with `run_record.json` differing only in `input` (display form) and `run_id` (C-R-CLI-2, FR-007, SC-001); bytes served for a coarse-level run are ≤ 1.10 × (stored bytes of that level + metadata documents) (SC-002, FR-008); a missing path raises `RemoteStoreError(cause="not_found")`, a stopped server raises `cause="network"`, neither is a `ValidationError` (C-LOC-7, FR-010); a v0.4 store served remotely gets the same "requires OME-Zarr v0.5" `ValidationError` message as locally (FR-006)
- [X] T010 [P] [US1] Add to `tests/contract/test_cli_mask.py` CLI read cases: `mask <http-url> <local out>` exits 0 and the output passes `assert_ome_zarr_models_valid`; `mask ftp://x/y out` and `mask https://u:p@h/x out` exit 1 with one stderr line, nothing on stdout, no output created and no `u:p` in stderr (C-R-CLI-1, C-R-CLI-7, C-LOC-2/3); the input log and run record show the URL as given/display form (C-R-CLI-8, FR-011)
- [X] T011 [P] [US1] Write the read half of `tests/integration/test_remote_s3.py` (moto fixture): upload the synthetic store to `s3://in/vol.ome.zarr`, mask to a local output, compare with the local-input run (C-R-CLI-2); the `https://in.s3.amazonaws.com/vol.ome.zarr` form gives the same result; with credentials env removed and a public-read bucket the read succeeds anonymously (C-LOC-8, US1 scenario 2); a bucket policy denying access raises `cause="forbidden"` (implementation note: moto does not enforce bucket policies, so `forbidden` is covered by the error-mapping tests in `tests/unit/test_location.py`)

### Implementation for User Story 1

- [X] T012 [US1] Change `validate_ome_zarr` in `src/ome_zarr_masker/io/validate.py` to accept `str | Path | StoreLocation`: parse with `StoreLocation.parse`; keep the local branch byte-for-byte; for remote, check existence and sniff the version by reading the root `zarr.json` through `open_store(read_only=True)` inside `remote_errors(...)`, then run the same `ome_zarr_models.open_ome_zarr` validation on the store object, so messages match local (FR-006); missing root document → `RemoteStoreError(cause="not_found")`, never `ValidationError`
- [X] T013 [US1] Change `OmeZarrReader.__init__` in `src/ome_zarr_masker/io/reader.py` to accept `str | Path | StoreLocation`, store `self.location`, keep `self.store_path` as the local `Path` (or `None` for remote) for existing callers, and open the group and level arrays through `self.location.open_store(read_only=True)` wrapped in `remote_errors(...)`; `read_level` reads only the selected level array (FR-008). Local behaviour unchanged
- [X] T014 [US1] Update `src/ome_zarr_masker/engine/pipeline.py`: parse the input once with `StoreLocation.parse(input_path)` before validation, pass the location to `validate_ome_zarr` and `OmeZarrReader`, and record `location.display` as the run record's `input` (local paths unchanged)
- [X] T015 [US1] Update `src/ome_zarr_masker/cli.py`: `mask` and `interactive` `input` help text says "Path or URL (http(s)://, s3://, gs://, az://, abfs://) of the input OME-Zarr v0.5 store"; catch `RemoteStoreError` in `_cmd_mask` and `_cmd_interactive` and print `error: <message>` to stderr with exit 1 (C-R-CLI-7); confirm `src/ome_zarr_masker/input_log.py` logs the argument as given (implementation note: the log is written before a credential-bearing URL is rejected, so the CLI now passes the command line and arguments through `redact_url` first, FR-011)
- [X] T016 [US1] Run `uv run pytest -q tests/unit/test_location.py tests/integration/test_remote_read.py tests/integration/test_remote_s3.py tests/contract/test_cli_mask.py` and the full non-slow suite; fix until green. Commit "feat(io): read OME-Zarr inputs from remote stores (010 US1)"

**Checkpoint**: Remote inputs work for `mask` with local outputs; MVP deliverable

---

## Phase 4: User Story 2 - Prompt interactively on a remote input (Priority: P2)

**Goal**: `interactive` and `OrganMaskPredictor.set_volume` read remote inputs; `InteractiveSession.export` refuses remote outputs.

**Independent Test**: quickstart.md step 5 (interactive/API read half).

### Tests for User Story 2 (write first, must fail)

- [X] T017 [P] [US2] Write `tests/integration/test_remote_api.py` (HTTP fixture): `InteractiveSession(<url>, level=...)` `read_volume()` equals the local read and a `preview()` with a stub backend matches the local-store preview (US2 scenario 1); saved prompts are a local file reusable by a run on the URL and on the local copy (US2 scenario 2; implementation note: the session has no prompt-saving API, so the test checks that the session preview on the URL equals `mask` runs with the equivalent local prompt file on the URL and on the local copy); `OrganMaskPredictor().set_volume(<url>)` succeeds (C-R-API table); `InteractiveSession.export("s3://b/m.ome.zarr")` and `export("https://h/m.ome.zarr")` raise `RemoteStoreError(cause="not_writable")` whose message says remote output is supported by `mask` and `MaskResult.save`, before any preview/compute runs (assert the backend was not called) and nothing is written (C-R-API-3, FR-004); `export(<local path>)` is unchanged

### Implementation for User Story 2

- [X] T018 [US2] Update `OrganMaskPredictor.set_volume` in `src/ome_zarr_masker/api.py` to parse `store_path` with `StoreLocation.parse` and pass the location to `validate_ome_zarr` and `OmeZarrReader` (signature unchanged: `str | Path`)
- [X] T019 [US2] Update `src/ome_zarr_masker/interactive.py`: `InteractiveSession.__init__` parses and keeps a `StoreLocation` (validating as today), `read_volume` and preview paths open `OmeZarrReader(self._location)`; at the top of `export`, parse `output_path` and if `is_remote` raise `RemoteStoreError(cause="not_writable", ...)` with the C-R-API-3 message before calling `preview`
- [X] T020 [US2] Run `uv run pytest -q tests/integration/test_remote_api.py` and the full non-slow suite; fix until green. Commit "feat(interactive): open remote inputs and refuse remote export (010 US2)"

**Checkpoint**: Interactive and API reading of remote inputs work; US1 still green

---

## Phase 5: User Story 3 - Write the mask to a remote store (Priority: P3)

**Goal**: `mask` and `MaskResult.save` write to S3, GCS and Azure with the commit-last protocol; generic HTTP outputs and same-store input/output are rejected before any work.

**Independent Test**: quickstart.md steps 3 (write half), 4 and 5 (save half).

### Tests for User Story 3 (write first, must fail)

- [ ] T021 [P] [US3] Add the write half to `tests/integration/test_remote_s3.py` (moto): mask `s3://in/vol.ome.zarr` → `s3://out/mask.ome.zarr`; download and check `assert_ome_zarr_models_valid` and equality with a local output of the same run (data, metadata, layout, run record apart from `run_id`/output location) (C-R-CLI-3, FR-007); empty shards are not written (009 behaviour); a second run without `--overwrite` exits 1 before segmentation (stub backend not called) and with `--overwrite` replaces the store (C-R-CLI-4); input and output naming the same store in different forms (`s3://in/vol.ome.zarr` and `https://in.s3.amazonaws.com/vol.ome.zarr/`) fail before any work (C-R-CLI-6); output `https://example.org/m.ome.zarr` exits 1 before computing with a message naming the writable forms (C-LOC-5, US3 scenario 4)
- [ ] T022 [P] [US3] Write `tests/integration/test_remote_write_failures.py` (`memory_fs` + `FailingFileSystem`): for N in {1, a mid-write value, total puts − 1}, `write_mask` to `s3://out/m.ome.zarr` raises `RemoteStoreError` naming the location and cause; afterwards the prefix has no root `zarr.json` and `validate_ome_zarr` on it raises (not a valid store) (C-R-CLI-5, FR-009, SC-005); a failure during overwrite also leaves no root `zarr.json`; a successful write puts the root `zarr.json` last (record the put order)
- [ ] T023 [P] [US3] Add to `tests/integration/test_remote_api.py`: `MaskResult.save("s3://out/api.ome.zarr")` (moto) equals the CLI output for the same inputs (C-R-API-1); it follows the overwrite and same-store rules (C-R-API-2); `MaskResult.save("https://example.org/x.ome.zarr")` raises `not_writable`

### Implementation for User Story 3

- [ ] T024 [US3] Add the remote branch of `write_mask` in `src/ome_zarr_masker/io/writer.py` (research R5), leaving the local temp-dir-then-rename branch unchanged: parse `output_path` with `StoreLocation.parse`; refuse `not_writable`; open `open_store(read_only=False)` inside `remote_errors(...)`; (1) if the root `zarr.json` exists and not `overwrite`, raise `WriterError` with the same message as local; (2) with overwrite, delete the root `zarr.json` first, then the rest of the prefix; (3) `image.to_zarr(store, path="")`, then read and delete the root `zarr.json`, keeping its bytes; (4) write every level with the existing shard planning and worker logic (empty shards skipped) and `run_record.json`; (5) put the root `zarr.json` last. On any exception, best-effort delete of the prefix and re-raise mapped through `map_remote_error`. Return the location (keep returning `Path` for local)
- [ ] T025 [US3] Update `src/ome_zarr_masker/engine/pipeline.py`: parse the output location before validation and segmentation; raise `not_writable` for generic HTTP outputs and a `PipelineError`/`RemoteStoreError` for remote input and output where `same_store` is true, both before any work (C-R-CLI-6, C-LOC-5); check the existing-output/overwrite rule up front for remote outputs as is done for local; record `location.display` for the output wherever the run record or input log records it
- [ ] T026 [US3] Update `MaskResult.save` in `src/ome_zarr_masker/api.py` to accept URL strings (signature unchanged) and pass them to `write_mask`; update `mask` `output` help text in `src/ome_zarr_masker/cli.py` to "Path or URL (s3://, gs://, az://, abfs://, or an HTTPS link on those providers' hosts) of the output store"
- [ ] T027 [US3] Run `uv run pytest -q tests/integration/test_remote_s3.py tests/integration/test_remote_write_failures.py tests/integration/test_remote_api.py` and the full non-slow suite; fix until green. Commit "feat(writer): write masks to S3, GCS and Azure with commit-last (010 US3)"

**Checkpoint**: All three stories work independently and together

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T028 [P] Write `tests/integration/test_remote_live.py` marked `remote_live`: for each of `OME_ZARR_MASKER_TEST_S3_URL`, `_GCS_URL`, `_AZURE_URL` that is set, write a synthetic mask under a unique sub-prefix with `write_mask`, read it back with `OmeZarrReader`, compare with a local write of the same mask, and delete the sub-prefix; each provider skips independently when its variable is unset (quickstart step 6, research R7)
- [ ] T029 [P] Update `README.md`: remote inputs/outputs with one example per provider, the accepted URL forms (link to the store-location contract), the extras (`[s3]`, `[gcs]`, `[azure]`, `[http]`, `[remote]`), ambient credentials per provider and anonymous access, the rejection of credentials in URLs, `interactive` export being local-only, and the remote-overwrite caveat (C-R-CLI-4)
- [ ] T030 [P] Update `docs/run-record.md`: `input` (and any output location field) holds the display form for remote locations (`s3://…`, `gs://…`, `az://… (account …)`, HTTP URL); credentials can never appear because such URLs are rejected
- [ ] T031 Confirm no local regression (SC-004, Constitution IV): run `uv run pytest -q -m slow tests/performance tests/integration/test_us3_level_speed.py` and compare with the feature 009 budgets; confirm `import ome_zarr_masker.cli` imports none of `fsspec`, `s3fs`, `gcsfs`, `adlfs`, `aiohttp` (add an assertion in `tests/unit/test_location.py` via `sys.modules` in a subprocess)
- [ ] T032 Run `uv run ruff check src tests`, `uv run ruff format --check src tests` and `uv run pytest -q`; walk quickstart.md steps 1–5 and 7 and record the outcome; mark the quickstart validated. Commit "docs: document remote store support (010)"

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none
- **Foundational (Phase 2)**: after Setup; blocks all stories
- **US1 (Phase 3)**: after Foundational
- **US2 (Phase 4)**: after Foundational; uses the reader/validator changes of T012–T013, so start it after those two tasks (or after US1)
- **US3 (Phase 5)**: after Foundational; T025's same-store check and its tests use remote input reading (T012–T014), so run after US1
- **Polish (Phase 6)**: after the stories it documents

### Within each story

- Tests first and failing, then implementation, then the story's green-and-commit task
- validate.py and reader.py (T012, T013) before pipeline.py (T014); writer.py (T024) before pipeline/API (T025, T026)

### Parallel Opportunities

- T003 can be written alongside T005 (test-first: confirm it fails, then implement)
- T009, T010, T011 (three different test files)
- T017 can be written while US1 implementation proceeds
- T021, T022, T023 (different test files; T023 only appends to `test_remote_api.py` after T017)
- T028, T029, T030 (different files)

---

## Parallel Example: User Story 1

```text
Task: "T009 Write tests/integration/test_remote_read.py"
Task: "T010 Add CLI read cases to tests/contract/test_cli_mask.py"
Task: "T011 Write read half of tests/integration/test_remote_s3.py"
```

## Parallel Example: User Story 3

```text
Task: "T021 Add write half to tests/integration/test_remote_s3.py"
Task: "T022 Write tests/integration/test_remote_write_failures.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup, Phase 2 Foundational
2. Phase 3 US1: remote inputs for `mask` with local output
3. Stop and validate with quickstart steps 1–3 (read half); this alone removes the download step

### Incremental Delivery

1. Foundation, then US1, committed (MVP)
2. US2: interactive and API reading, export refusal, committed
3. US3: remote output with commit-last, committed
4. Polish: live tests, docs, regression check, committed

Commits follow plan.md's Constitution III plan: location parser → read path → write path →
API/interactive rules → docs, each green.
