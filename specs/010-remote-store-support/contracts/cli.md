# Contract: CLI changes

**Feature**: 010-remote-store-support | **Date**: 2026-10-22

Extends `specs/001-ome-zarr-sam-masking/contracts/cli.md` and
`specs/009-scalable-mask-writer/contracts/cli.md`. No new options or flags: `INPUT` and `OUTPUT`
additionally accept the URL forms of `contracts/store-location.md`.

## `ome-zarr-masker mask INPUT OUTPUT ...`

- C-R-CLI-1: `INPUT` may be any readable form; `OUTPUT` any writable form. Local paths behave
  exactly as before (FR-012, SC-004).
- C-R-CLI-2: For the same store contents and options, a run with a remote `INPUT` writes an output
  identical to the run on a local copy: same level data, metadata and layout; in `run_record.json`
  only `input` (the location's display form) and `run_id` differ (FR-007, SC-001).
- C-R-CLI-3: A remote `OUTPUT` is identical to a local `OUTPUT` of the same run (data, metadata,
  layout, run record) and passes ome-zarr-models' validation (US3).
- C-R-CLI-4: A remote `OUTPUT` whose root `zarr.json` exists fails before segmentation without
  `--overwrite`; with `--overwrite` it is replaced. Note: on a failed remote overwrite the previous
  store has already been removed (research R5); locally it survives, as today.
- C-R-CLI-5: If a remote write fails, the command exits 1, names the location and cause, and the
  output location has no root `zarr.json` (it cannot be opened as OME-Zarr) (FR-009, SC-005).
- C-R-CLI-6: A remote `INPUT` and remote `OUTPUT` resolving to the same store fail before any work.
- C-R-CLI-7: Every location error (`RemoteStoreError`) and every validation error exits 1 with a
  single-line message on stderr and nothing on stdout; no output is created.
- C-R-CLI-8: The input log and `run_record.json` record locations as given / as their display form;
  neither can contain credentials (C-LOC-3).

## `ome-zarr-masker interactive INPUT ...`

- C-R-CLI-9: `INPUT` may be any readable form; the session behaves as for a local store
  (US2). Prompt files and logs remain local.
