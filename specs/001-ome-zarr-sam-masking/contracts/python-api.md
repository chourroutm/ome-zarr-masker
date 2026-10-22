# Contract: Python API (SAM-like)

**Feature**: 001-ome-zarr-sam-masking | **Date**: 2026-06-14

The public API mirrors the structure of the SAM/SAM2 predictor API so SAM users adopt it with
minimal learning (FR-010, SC-004). It is a thin facade over the shared engine.

## Entry point: `OrganMaskPredictor`

```python
from organ_masker_lite import OrganMaskPredictor

predictor = OrganMaskPredictor(backend="sam2", model_dir=None, allow_download=True)
predictor.set_volume("input.ome.zarr", level=3)            # mirrors SAM set_image
predictor.add_points(frame_index=120, point_coords=[[x, y]], point_labels=[1])
mask = predictor.predict(axes=["z"], direction="forward")  # returns a mask handle
mask.save("output.ome.zarr")
```

### Constructor

`OrganMaskPredictor(backend="sam2", model_dir=None, allow_download=True)`
- `backend`: `"sam2"` (default) or `"sam3"` (FR-018).
- `model_dir`: override the default `./organ_masker_models` (FR-019). `None` => default/env.
- `allow_download`: auto-download missing weights when true; else error if absent (FR-020).

### `set_volume(store_path, level=<default>)`
- Validates the store in-process via `ome-zarr-models` (FR-001), selects the level (FR-003), prepares
  lazy slice access. Mirrors SAM's `set_image`.

### Prompt methods (SAM-convention arguments)
- `add_points(frame_index, point_coords, point_labels, obj_id=0)`
  - `point_coords`: array-like `(N, 2)` of `(x, y)`.
  - `point_labels`: array-like `(N,)`; `1`=positive, `0`=negative (exclusion). Same convention as
    the SAM2 prompt encoder (research R4).
- `add_box(frame_index, box, obj_id=0)`
  - `box`: `[x_min, y_min, x_max, y_max]`.
- Both may be called multiple times and combined; argument names/shapes match SAM2's
  `add_new_points_or_box`.

### `predict(axes=None, direction="forward", combine_rule="majority", postprocess=None) -> MaskResult`
- `axes`: sweep axes; default single axis (P1).
- `direction`: `"forward"` or `"forward_reverse"` (FR-006).
- `combine_rule`: `"majority"` (default), `"union"`, `"intersection"` (FR-007).
- `postprocess`: `PostProcessConfig` or `None` for defaults (fill-holes on).
- Returns a `MaskResult` equivalent to the CLI output for identical inputs/prompts (SC-005).

### `MaskResult`
- `.array` — the consensus mask at the run level (NumPy/lazy).
- `.save(store_path, overwrite=False, *, workers=None, progress=None)` — writes OME-Zarr v0.5 with
  the **same levels as the input** (research R5), refusing to overwrite unless `overwrite=True`
  (FR-013), and embedding the run record (FR-014). Since feature 009 each level is written shard by
  shard (sharded, compressed); `workers`/`progress` are described in
  `specs/009-scalable-mask-writer/contracts/python-api.md`.

## Behavioral contract (testable)

- C-API-1: With one positive point (label `1`) on a frame, `predict` returns a non-empty mask whose
  foreground includes that point's location. *(US1, first feature to test)*
- C-API-2: With a `box`, `predict` returns a mask whose foreground lies predominantly within the box
  on the prompt frame. *(US1, second feature to test)*
- C-API-3: Adding a negative point (label `0`) inside an otherwise-positive region excludes that
  region from the foreground. *(US1, third feature to test)*
- C-API-4: A run with no positive point and no box raises a clear validation error (FR-015).
- C-API-5: Out-of-bounds coordinates for the selected level raise a clear validation error (FR-015).
- C-API-6: API and CLI produce equivalent masks for identical inputs/prompts (SC-005).
- C-API-7: `backend="sam3"` runs the same flow and produces a comparable mask object (SC-010).
- C-API-8: Saved output has the same level count as the input and is valid OME-Zarr v0.5 (SC-002).
- C-API-9: Argument names/shapes for points/labels/box match SAM2's `add_new_points_or_box`.
