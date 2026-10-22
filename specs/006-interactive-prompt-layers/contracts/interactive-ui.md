# Interactive Session UI Contract: Prompt Layers

Extends the `interactive` subcommand's existing contract (napari session launched by
`ome-zarr-masker interactive <input>`). Supersedes the single "prompts" points layer described
implicitly by the current `launch()` implementation; all other `interactive` subcommand clauses
(input/level/model-dir/no-download arguments) are unchanged.

## Layers

- **C-UI-1**: On launch, the viewer MUST contain exactly three prompt layers in addition to the
  `volume` image layer: `positive-points`, `negative-points`, `positive-box`. No single combined
  "prompts" layer is created (FR-001).
- **C-UI-2**: A point placed via napari's default add-point interaction MUST land in
  `positive-points` (FR-002).
- **C-UI-3**: `positive-points` MUST render markers as a lime cross, size 7, no edge (FR-005).
- **C-UI-4**: `negative-points` MUST render markers as a red disc, size 6, no edge (FR-006).
- **C-UI-5**: `positive-box` MUST only ever contain rectangle shapes; any other shape type drawn
  in it MUST be removed rather than persisted (FR-007).
- **C-UI-6**: `positive-box` MUST render with `translucent_no_depth` blending, opacity 1.0, a 1px
  lime edge, and `#00000000` fill (FR-008).

## Keybindings

- **C-UI-7**: `n` and `y` MUST be bound at the viewer level (`viewer.bind_key`), not per-layer.
- **C-UI-8**: `n` MUST move the current selection in `positive-points` into `negative-points`; a
  point already in `negative-points` is unaffected by `n` (no-op) (FR-003).
- **C-UI-9**: `y` MUST move the current selection in `negative-points` into `positive-points`; a
  point already in `positive-points` is unaffected by `y` (no-op) (FR-004).
- **C-UI-10**: If both point layers hold a selection when `n` or `y` is pressed, both layers'
  corresponding effects MUST fire from the single keypress (FR-004 mixed-selection clause).
- **C-UI-11**: Whenever the active layer changes, the layer losing active status MUST have its
  `selected_data` cleared if it is `positive-points` or `negative-points` (FR-004a).
- **C-UI-12**: Immediately after `n`/`y` moves point(s), the destination layer's `selected_data`
  MUST be set to the moved point(s)' new indices, so an immediate opposite keypress flips them back
  with no reselection (FR-004b).
- **C-UI-13**: `p` (preview) and `e` (export) MUST resync the headless core from all three layers
  before computing/exporting: points from `positive-points`/`negative-points`, and at most one
  rectangle per frame from `positive-box` (replacing on redraw per FR-010), merged per frame into
  one `Prompt`/one `OrganMaskPredictor.add_prompts(..., box=...)` call (research R2 — required to
  avoid SAM2 silently dropping one of two separate per-frame calls).

## Headless core (`InteractiveSession`, napari-independent)

- **C-UI-14**: `add_box(frame_index, box)` MUST replace any existing box for that `frame_index`
  (FR-010) and invalidate the cached preview.
- **C-UI-15**: `preview()`/`export()` output for a given set of points+box MUST be identical
  whether those points/box were supplied via this UI or via an equivalent CLI prompt-file with the
  same coordinates/labels/box (SC-004) — both paths now construct one `Prompt` per frame.
