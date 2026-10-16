# Phase 1 Data Model: Level-Agnostic Prompt Coordinates

**Feature**: 008-level-agnostic-prompts | **Date**: 2026-10-09

This extends the `Prompt`/`PromptSet` entities defined in
`specs/001-ome-zarr-sam-masking/data-model.md`. Only the fields/behavior that change are repeated
here; everything else (labels, obj_id, box shape, etc.) is unchanged.

## Prompt (unchanged fields; unchanged shape)

| Field | Type | Notes |
|-------|------|-------|
| `frame_index` | int | Slice index along the active sweep axis, in **its `PromptSet`'s authoring level's grid** until resolved to a run level |
| `point_coords` | ndarray `(N,2)` float | `(x, y)`, in the same authoring-level grid |
| `point_labels` | ndarray `(N,)` int | unchanged |
| `box` | ndarray `(4,)` float or None | unchanged shape; same authoring-level grid |
| `obj_id` | int | unchanged |

No new field on `Prompt` itself (see research.md R2: the authoring level is tracked once per
`PromptSet`, not per `Prompt`).

## PromptSet (new field + new behavior)

| Field | Type | Notes |
|-------|------|-------|
| `prompts` | `list[Prompt]` | unchanged |
| `level` | `int \| None` | **NEW.** The pyramid level whose pixel grid `prompts`' coordinates are expressed in. `None` means "already in whatever level this set is used at" (the default for prompt sets not produced by one of the two authoring paths below -- internal/test construction, pipeline-internal seed prompts for secondary sweep axes). |

### New method: `resolved_for_shape(src_shape, dst_shape, axis_index) -> PromptSet`

Converts every prompt's `frame_index`/`point_coords`/`box` from one level's pixel grid to another's.

- **Identity**: returns `self` unchanged when `src_shape == dst_shape` (FR-006).
- **Otherwise**: for each of the three axes, computes `dst_shape[axis] / src_shape[axis]` and scales
  the matching coordinate component by that axis's own ratio (FR-004) -- `frame_index` by the sweep
  axis's ratio; `x`/box `x0,x1` by the in-plane "width" axis's ratio; `y`/box `y0,y1` by the in-plane
  "height" axis's ratio, using the same height/width-axis convention as `PromptSet.validate()`.
  Rounds to the nearest pixel.
- Returns a new `PromptSet` with the same `level` (the caller is expected to then validate/use the
  *shapes* passed in, not re-read `.level` off the result).

### `to_record()` -- changed return shape

| Before (feature 001-007) | After (this feature) |
|---|---|
| `list[dict]` -- one dict per prompt | `{"level": int \| None, "objects": list[dict]}` -- the per-prompt dicts are unchanged, now under `"objects"` |

Chosen so the saved run-record's prompt section and the loadable prompt-file format (below) are
structurally identical (research.md R5) -- a saved file's authoring level is visible without
computing anything (spec User Story 2, SC-003).

## Prompt file (on-disk JSON) -- schema change

```json
{
  "level": 4,
  "objects": [
    {
      "obj_id": 0,
      "points": [{"frame": 120, "xy": [340, 512], "label": 1}],
      "box": {"frame": 120, "xyxy": [300, 480, 380, 560]}
    }
  ]
}
```

- **`level`** (new, **required**, int): the pyramid level these coordinates were read off of. A file
  missing this key is rejected with a clear `PromptError` (FR-007) -- it is treated as a stale,
  pre-feature file, never silently reinterpreted as level-0 or run-level coordinates.
- `objects` and everything inside it: unchanged from feature 001.

## Validation rules (additions to feature 001's)

- `PromptSet.level`, when not `None` and not equal to the run level, MUST be a valid level index for
  the current input (`0 <= level < reader.n_levels`); otherwise a clear `PromptError` naming the
  requested and available levels is raised (FR-008), *before* any shape-ratio conversion is attempted.
- The existing bounds checks in `PromptSet.validate()` (frame index in range, point/box coordinates
  within the plane) run **after** conversion, against the *run* level's shape -- a coordinate that
  rounds to just outside the run level's bounds after conversion is still rejected (spec Edge Cases),
  even though it was valid at its own authoring level.

## State / lifecycle

Unchanged from feature 001 (prompts are immutable once added to a run), with one new step inserted
into `engine/pipeline.py::compute_mask`, between resolving the run level's shape and validating:

```
reader.resolve_level(config.level) -> level_shape
    -> [NEW] if prompts.level not in (None, level): check prompts.level is a valid index,
             then prompts = prompts.resolved_for_shape(reader.level_shape(prompts.level),
                                                         level_shape, prompted_index)
    -> prompts.validate(level_shape, prompted_index)   # unchanged from feature 001
```
