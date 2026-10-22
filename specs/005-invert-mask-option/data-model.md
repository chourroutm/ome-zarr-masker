# Phase 1 Data Model: Invert Mask Output Option

This feature introduces no new domain entity. It adds one field to an existing configuration
dataclass and changes the derived values that depend on it.

## `PostProcessConfig` (`src/ome_zarr_masker/config.py`)

Existing fields (unchanged):

| Field | Type | Default | Meaning |
|---|---|---|---|
| `fill_holes` | `bool` | `True` | Fill interior holes in the mask |
| `dilation_radius` | `int` | `0` | Dilation radius in voxels |
| `erosion_radius` | `int` | `0` | Erosion radius in voxels |

New field:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `invert` | `bool` | `False` | Swap the final mask's binary values (organ `1`/background `0` → organ `0`/background `1`) (FR-003, FR-006) |

Derived value changes:

- **`is_noop` property**: currently `not self.fill_holes and self.dilation_radius == 0 and
  self.erosion_radius == 0`. MUST become `... and not self.invert`, so a run with only `--invert`
  set is correctly treated as non-trivial post-processing rather than skipped.
- **`RunConfig.to_record()`**: the `postprocess` sub-dict (currently `fill_holes`,
  `dilation_radius`, `erosion_radius`) MUST add `"invert": self.postprocess.invert`, so the
  reproducibility run-record (FR-014 of spec 001) captures whether a given run's output was
  inverted.

No validation rule is needed for `invert` beyond its type (a plain `bool` has no invalid range,
unlike `dilation_radius`/`erosion_radius`).

## Mask array (in-memory / on-disk)

No shape or dtype change. The binary mask stays a 3D array that is `{0, 1}` as `uint8` on disk
(`io/writer.py`, unchanged) and boolean in memory while `postprocess_mask()` operates on it
(unchanged). `--invert` only flips which of the two values means "organ" versus "background"; it
does not add a third value, change array rank, or affect the multiscale pyramid structure.

## State / ordering

`postprocess_mask()`'s existing fixed order — dilation, then erosion, then fill-holes — gains one
more step at the end:

```text
dilate → erode → fill_holes → invert
```

This ordering is a hard requirement (FR-004): each earlier step always operates on the
organ-labeled region, never on the inverted background, regardless of whether `--invert` is set.
