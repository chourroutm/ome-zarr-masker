# Phase 1 Data Model: OME-Zarr Organ Masking with SAM

**Feature**: 001-ome-zarr-sam-masking | **Date**: 2026-06-14

Entities are in-memory/on-disk domain objects (this feature has no database). Field names are
indicative of the Python API.

## InputVolume

Represents the validated OME-Zarr v0.5 multiscale input.

| Field | Type | Notes |
|-------|------|-------|
| `store_path` | path | Filesystem path to the OME-Zarr v0.5 store |
| `levels` | list[LevelInfo] | Ordered finest..coarsest as declared by the multiscale metadata |
| `axes` | list[str] | Axis names/order from OME metadata (e.g. `["z","y","x"]`) |

Validation rules:
- MUST pass in-process OME-Zarr v0.5 validation via `ome-zarr-models` before use (FR-001);
  otherwise construction fails.
- MUST expose >= 1 level.

## LevelInfo

One multiscale level (binning level).

| Field | Type | Notes |
|-------|------|-------|
| `index` | int | 0 = finest |
| `shape` | tuple[int,...] | Per-axis voxel sizes |
| `coordinate_transformations` | list | Scale/translation from OME metadata; preserved on output |
| `array` | zarr array (lazy) | Streamed slice-wise, never fully loaded |

## Prompt (SAM2-compatible)

A landmark on a specific slice/frame. Mirrors the SAM2 prompt-encoder convention (see research R4).

| Field | Type | Notes |
|-------|------|-------|
| `frame_index` | int | Slice index along the active sweep axis where the prompt is placed |
| `point_coords` | ndarray `(N,2)` float | `(x, y)` in the slice's pixel space |
| `point_labels` | ndarray `(N,)` int | `1`=positive/include, `0`=negative/exclude |
| `box` | ndarray `(4,)` float or None | `[x_min, y_min, x_max, y_max]` |
| `obj_id` | int | Internal single-object identifier; multi-object segmentation is out of scope (FR-021) |

Validation rules:
- `point_coords` length MUST equal `point_labels` length.
- Across the full PromptSet there MUST be at least one positive point or a box (FR-015).
- Coordinates MUST fall within the selected level's bounds (FR-015); else reject. As of feature
  008-level-agnostic-prompts, this check runs *after* converting the coordinates to the run level's
  grid (see `PromptSet.level` below) -- bounds are always enforced against the level actually used.
- Labels MUST be in `{0, 1}` at the API surface; box-corner labels `2/3` and padding `-1` are
  produced internally by the backend, never supplied by the user.

State / lifecycle: prompts are immutable once added to a run; the interactive mode rebuilds the
PromptSet between previews.

## PromptSet

Ordered collection of `Prompt`s for one run, grouped by `obj_id` and `frame_index`. Serializable to
/from the CLI prompt file. Records the three first-to-test shapes:
1. single positive point, 2. box, 3. positive + exclusion (negative) point.

| Field | Type | Notes |
|-------|------|-------|
| `level` | `int \| None` | **(feature 008-level-agnostic-prompts)** The pyramid level this set's coordinates were authored against; `None` means "already in whatever level this set is used at". A loaded prompt file or an `OrganMaskPredictor` session always sets it; direct construction defaults to `None`. |

When `level` differs from the level a run actually uses, every coordinate (`frame_index`,
`point_coords`, `box`) is converted to the run level's pixel grid -- via each axis's own shape
ratio between the two levels, nearest-pixel rounding -- before validation. See
`specs/008-level-agnostic-prompts/data-model.md` for the full mechanism, and
`specs/008-level-agnostic-prompts/contracts/prompt-file-format.md` for the on-disk schema.

## RunConfig

The complete, reproducible parameterization of a run (FR-014).

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `backend` | enum {`sam2`,`sam3`} | `sam2` | First-class backends (FR-018) |
| `level` | int | coarsest level (highest index) | Selected binning level (FR-003) |
| `axes` | list[axis] | single axis (P1) | One or more sweep axes (FR-007) |
| `direction` | enum {`forward`,`forward_reverse`} | `forward` | Propagation mode (FR-006) |
| `combine_rule` | enum {`majority`,`union`,`intersection`} | `majority` | Consensus rule (FR-007) |
| `postprocess` | PostProcessConfig | see below | Optional cleanup (FR-012) |
| `model_dir` | path | `./ome_zarr_masker_models` | Override via option/env (FR-019) |
| `allow_download` | bool | `true` | `--no-download` sets false (FR-020); download is performed by an injectable fetcher so the path is unit-testable without network |
| `overwrite` | bool | `false` | Guards existing output (FR-013) |

Validation rules:
- `level` MUST exist in the input; else report available levels and abort (FR-003).
- `backend` weights MUST be resolvable per `model_dir`/`allow_download` (FR-020).

## PostProcessConfig

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `fill_holes` | bool | `true` | Enabled by default (research R8) |
| `dilation_radius` | int | `0` | Disabled by default |
| `erosion_radius` | int | `0` | Disabled by default |

## Sweep (runtime, transient)

One traversal of the volume as ordered slices along one axis in one direction.

| Field | Type | Notes |
|-------|------|-------|
| `axis` | axis | Sweep axis |
| `direction` | enum | forward / reverse |
| `seed_source` | enum {`prompts`,`seeded`} | `prompts` for the prompted axis; `seeded` for other axes (FR-022) |
| `frame_store` | memmap ref | uint8 RGB frames for this sweep (research R3) |
| `result` | per-voxel binary contribution | Folded into the vote accumulator, not retained |

The prompted axis is swept first using the user's prompts; sweeps along the other selected axes are
seeded automatically from the prompted axis's 3D result rather than from new user prompts (FR-022).

## ConsensusMask (runtime, transient)

A single binary foreground mask for one target structure per run (FR-021).

| Field | Type | Notes |
|-------|------|-------|
| `votes` | memmap (uint) | Per-voxel count of sweeps marking foreground |
| `n_sweeps` | int | Number of contributing sweeps |
| `mask` | derived | `votes > n_sweeps/2` for majority (or union/intersection) |

## OutputMask

The written OME-Zarr v0.5 result.

| Field | Type | Notes |
|-------|------|-------|
| `store_path` | path | Destination store |
| `levels` | list[LevelInfo] | **Same count as input**; shapes/transforms copied from input (research R5) |
| `dtype` | binary `uint8` (0/1) | Single foreground mask, one structure per run (FR-021); nearest-neighbor resampled across levels |
| `run_record` | mapping | Serialized RunConfig + PromptSet for reproducibility (FR-014) |

Validation rules:
- Output level count MUST equal input level count.
- MUST be readable as valid OME-Zarr v0.5 (SC-002) and registerable against the input (same grids).
- MUST NOT overwrite an existing store unless `overwrite` is set, and MUST NOT leave a partial store
  on failure/interrupt (FR-013) — write to a temp store and atomically move into place on success.

## Relationships

- `InputVolume` 1..* `LevelInfo`; a `RunConfig.level` selects one `LevelInfo`.
- `RunConfig` references one `backend`; the backend resolves weights from `model_dir`.
- A run produces 1..* `Sweep` (axes x directions) folding into one `ConsensusMask`, which (after
  optional `PostProcessConfig`) becomes one `OutputMask` whose levels mirror the input.
- The prompted axis is swept first from the user's prompts; other selected axes are seeded from its
  3D result (FR-022). Each run yields a single binary foreground mask (FR-021).
