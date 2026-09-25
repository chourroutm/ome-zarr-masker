# Phase 0 Research: Interactive Prompt Layers (Points + Box)

## R1: Custom "prompt" napari layer type (new plugin dependency) vs. composing built-in layers

**Question raised**: should this feature build a new custom napari layer type, "prompt" — unifying
point add/select/delete (positive/negative), box add/select/resize/delete, and a swap action into
one native layer, distributed as a new napari-plugin dependency — instead of the three-built-in-
layers design (2× `Points` + 1× `Shapes`) already in spec.md?

**Decision**: No. Keep the three-built-in-layers design; do not add a new plugin dependency.

**Rationale**, from three independent checks:

1. **napari's plugin system has no "new layer type" extension point.** Inspecting the installed
   `npe2` package's contribution points directly (`npe2.manifest.contributions.ContributionPoints`)
   gives exactly: `commands, readers, writers, widgets, sample_data, themes, menus, submenus,
   keybindings, configurations`. A reader plugin can return data *for* one of napari's existing
   built-in layer types (via a `layer_type` string), but there is no hook for registering a wholly
   new `Layer` subclass with its own interaction model as a supported plugin. napari's own layer
   registry (`napari.layers.NAMES`) is a fixed set of seven: `image, labels, points, shapes,
   surface, tracks, vectors`, and `Layer.create(layer_type=...)` dispatches by name only to those.
   Registering a genuinely new layer type is only possible by reaching into undocumented internals
   (subclassing `Layer` directly and monkey-patching napari's private Qt-controls factory) — not a
   real "plugin" in the supported sense, and fragile across napari versions. Confirmed by direct
   inspection of the installed packages in this project's own `.venv`, and corroborated by a napari
   GitHub issue on the *existing* Labels layer ("Allow adding custom modes to the Labels layer",
   [napari/napari#2314](https://github.com/napari/napari/issues/2314)) showing that even extending
   an *existing* built-in layer's interaction modes is an open friction point in napari itself —
   let alone registering an entirely new layer type through the plugin API.
2. **No existing plugin does this, in this exact problem domain.** A search for napari + SAM
   (Segment Anything) point/box prompting plugins turns up several real, maintained examples, and
   every one composes napari's built-in layers rather than defining a new layer type:
   - [napari-segment-anything](https://github.com/royerlab/napari-segment-anything) (royerlab) —
     "Interactions are done on the 'SAM points' and 'SAM box' layers" (a `Points` layer + a
     `Shapes` layer), left/right-click for positive/negative.
   - [napari-SAM4IS](https://napari-hub.org/plugins/napari-sam4is.html) — a "SAM-Box" layer (built-
     in `Shapes`, rectangle tool) driving a separate prediction/labels layer.
   - [napari-sam3-assistant](https://github.com/wulinteousa2-hash/napari-sam3-assistant) — points,
     boxes, and exemplar prompts, again via napari's standard layer types.
   - [micro_sam](https://github.com/computational-cell-analytics/micro-sam) (EMBL, the most
     prominent/actively-maintained tool of this group) — a `point_prompts` `Points` layer, a
     `prompts` `Shapes` layer for the box, plus `committed_objects`/`current_object` `Labels`
     layers for output. Also built entirely from napari's built-in layer types, no custom type.
   This is strong, concrete prior art that the composed-built-in-layers pattern is how this exact
   problem is solved in practice, not a limitation specific to this project.

   One nuance worth recording for transparency, since it doesn't affect the R1 conclusion but does
   touch the spec's already-decided layer count: `micro_sam` uses a *single* `point_prompts` layer
   with positive/negative conveyed by a feature-based color column (green/red) — the same
   single-layer-with-color-feature pattern this project's own pre-006 code used — rather than two
   separate point layers. So even among "compose built-in layers, no custom type" implementations,
   there's a real split between one merged points layer and two separate ones; this project's
   two-layer choice (spec.md FR-001) was set directly by explicit user instruction ("3 layers for
   positive point, negative point and positive box"), not derived from ecosystem consensus, and is
   not reopened by this research — recorded here only so that choice is understood as a deliberate
   one, not an uninformed default.
3. **Nothing in the request is actually missing from the built-in composition.** Box
   add/select/resize/delete is already native `Shapes`-layer behavior (select mode + drag handles
   to resize, `Delete` key to remove) — no code needed beyond adding the layer with the FR-007/008
   styling. Point add/select/delete is already native `Points`-layer behavior, already used today.
   The "swap positive/negative" action is exactly what `n`/`y` (spec.md FR-003/004/004a/004b)
   already provide across the two point layers. A unified custom layer would change *where* this
   logic lives (inside a new layer class vs. our own event wiring around two standard layers), not
   *what* the user can do — so it buys no new capability, only new maintenance surface and a new
   dependency resting on undocumented napari internals.

**Alternatives considered**: build the custom layer type anyway (rejected: constitution Principle
I — "prefer the simplest solution that satisfies the requirement" — the composed approach already
satisfies every requirement); wrap the three layers in a *widget* (a supported plugin extension
point) that presents them as if unified in the UI, without a new layer type (deferred — genuinely
possible later as a polish pass, but adds a dock-widget dependency/UI surface not requested by
spec.md and not needed to satisfy any FR; can be revisited as a follow-up feature if the three-
layer UI proves confusing in practice).

## R2: Combining a frame's points and box into the masking engine

**Question**: `OrganMaskPredictor.add_points_or_box` and `.add_box` (`api.py:83-123`) each independently
append a *separate* `Prompt` object for a given frame. If a frame has both point prompts and a box
prompt, calling both methods for that frame produces two separate `Prompt` entries, which
`sam2.py`'s backend then sends to SAM2's `add_new_points_or_box` as two separate calls for the same
`(frame_index, obj_id)` — one with real points and no box, one with an empty points array and a
box. Does SAM2's video predictor correctly accumulate two such calls for the same frame, or could
the second call silently reset/override the first?

**Decision (hardened after reading the installed SAM2 source, not just inferred)**: confirmed
unsafe — merging is required, not optional. `SAM2VideoPredictor.add_new_points_or_box`'s default
`clear_old_points=True` means each call starts that frame's point inputs fresh
(`point_inputs = point_inputs_per_frame.get(frame_idx, None)` is only reused when
`clear_old_points=False`); `sam2.py:103` never overrides this default. So two separate calls for
the same frame — one points-only, one box-only — do **not** accumulate: whichever call happens
second silently discards the first's contribution. (The method also explicitly requires
`clear_old_points=True` whenever a box is given, since box+points must be encoded together as one
prompt — see its own `raise ValueError("cannot add box without clearing old points...")` guard.)
This is a real, confirmed data-loss bug if implemented naively, not a hypothetical.

The interactive session's `preview()` MUST therefore merge each frame's points and box into a
single `Prompt` — one predictor call per frame — before reaching SAM2. Mechanism: extend
`OrganMaskPredictor.add_points_or_box` (`api.py:83-104`) with a new optional `box: np.ndarray | None =
None` parameter threaded straight into the `Prompt(...)` it already constructs, so one call can
carry a frame's points and box together. `add_box` (`api.py:111-123`) stays as a thin,
backward-compatible convenience wrapper for the box-only case (unaffected, still calls the same
underlying `Prompt` construction). This is the one small `api.py` change this feature needs — the
plan's "no `api.py` changes" assumption from before this research was inaccurate and is corrected
here.

**Rationale**: Extending `add_points_or_box` with an optional `box` parameter is the minimal change that
avoids the confirmed accumulation bug — no new method, no reaching into `OrganMaskPredictor`'s
private `_prompts` list from `interactive.py`, and `add_box`'s existing callers/tests are
unaffected since its own behavior doesn't change. It also matches the CLI/batch prompt-file path,
where a single `Prompt` already carries both `point_coords`/`point_labels` and an optional `box`
together (`prompts/model.py:22-49`, `load_prompt_file` already merges per frame) — so this is not
a new shape, just reusing the one `Prompt` already models, consistent with FR-009's "same
underlying prompt model" requirement and directly serving SC-004 (interactive/CLI parity).

**Alternatives considered**: call `add_points_or_box` then `add_box` separately for a frame with both and
trust SAM2 to accumulate — ruled out by reading the source (confirmed unsafe, not just unverified);
have `interactive.py` construct `Prompt` objects itself and reach into
`OrganMaskPredictor._prompts` directly — rejected, breaks encapsulation across a private attribute
for no benefit over a one-parameter, backward-compatible `add_points_or_box` extension; add a wholly new
`add_prompt(...)` method instead of extending `add_points_or_box` — rejected as an unnecessary second
entry point for what `add_points_or_box` already does, just missing one optional parameter.
