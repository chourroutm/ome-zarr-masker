# Phase 1 Data Model: Interactive Prompt Layers (Points + Box)

No new domain entity or on-disk schema change. This feature restructures in-memory prompt
bookkeeping inside `InteractiveSession` and adds three napari view layers over it.

## `InteractiveSession` headless core (`src/organ_masker_lite/interactive.py`)

Existing state (unchanged in shape):

| Field | Type | Meaning |
|---|---|---|
| `_points` | `list[tuple[int, float, float, int]]` | `(frame_index, x, y, label)`, `label` 1=positive/0=negative |
| `_preview` | `MaskResult \| None` | Cached last-computed preview; invalidated on any prompt change |

New state:

| Field | Type | Meaning |
|---|---|---|
| `_boxes` | `dict[int, np.ndarray]` | `frame_index -> [x0, y0, x1, y1]`; at most one box per frame (FR-010) |

New/changed methods:

- **`add_box(frame_index: int, box) -> InteractiveSession`** (new): stores/replaces
  `_boxes[frame_index]`, invalidates `_preview`. Mirrors `add_point`'s shape.
- **`clear_boxes() -> InteractiveSession`** (new): empties `_boxes`, invalidates `_preview`.
  Kept separate from the existing `clear_points()` (which stays points-only) so the napari view's
  point-layer resync and box-layer resync remain independent operations.
- **`preview(...)`** (changed): still groups `_points` by frame, but now also looks up
  `_boxes.get(frame)` for each frame that has either points or a box, and calls
  `self._predictor.add_points_or_box(frame_index=frame, point_coords=coords, point_labels=labels,
  box=_boxes.get(frame))` — one call per frame carrying everything for that frame, per research R2.
  A frame with only a box and no points calls `add_points_or_box` with empty `coords`/`labels` arrays and
  the box, which is already valid input (mirrors `add_box`'s existing empty-points construction).

## `OrganMaskPredictor` (`src/organ_masker_lite/api.py`)

- **`add_points_or_box(frame_index, point_coords, point_labels, obj_id=0, *, box=None)`** (changed): new
  optional keyword-only `box` parameter, threaded into the single `Prompt` this method already
  constructs. Existing callers (CLI path via `sam2.py`'s wrapper is unaffected; nothing calls
  `add_points_or_box` without `box` today, so the default `None` preserves all current behavior
  byte-for-byte).
- **`add_box(frame_index, box, obj_id=0)`**: unchanged; remains a valid standalone box-only call.

## napari view layers (`InteractiveSession.launch()`)

Three layers replace the current single "prompts" points layer:

| Layer | napari type | Holds | Appearance (FR-005/006/008) |
|---|---|---|---|
| positive-points | `Points` | Include/positive landmark prompts | Cross symbol, size 7, lime fill, no edge |
| negative-points | `Points` | Exclude/negative landmark prompts | Disc symbol, size 6, red fill, no edge |
| positive-box | `Shapes` (rectangle-only) | At most one box prompt per frame | `translucent_no_depth` blending, opacity 1.0, 1px lime edge, `#00000000` fill |

State kept only in the napari layers themselves (their `.data`/`.selected_data`); the headless core
(`_points`, `_boxes`) is resynced from the layers on each `p`(preview)/`e`(export) keypress, exactly
as `_sync_points_from_layer()` already does today for the single points layer — extended to also
sync the negative-points layer and the positive-box layer (keeping at most one rectangle per frame,
per FR-010's replace-on-redraw rule).

## Selection / keybinding state (FR-003/004/004a/004b)

No new persisted entity — this is pure napari `Layer.selected_data` (a `set[int]` per layer,
already built into napari) plus two new pieces of event wiring in `launch()`:

- A callback on the viewer's active-layer-change event that clears the outgoing layer's
  `selected_data` when it's one of the two point layers (FR-004a).
- The `n`/`y` key handlers, after moving point(s) between layers, explicitly set the destination
  layer's `selected_data` to the indices of the just-moved points (FR-004b).
