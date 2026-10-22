# Phase 0 Research: OME-Zarr Organ Masking with SAM

**Feature**: 001-ome-zarr-sam-masking | **Date**: 2026-06-14

This document records the technical decisions resolving the planning unknowns and the directives in
the `/speckit-plan` input.

## R1. OME-Zarr v0.5 reading/writing and validation

**Decision**: Use `zarr` (v3) for array IO and `ome-zarr-models` for metadata parsing/validation.
Validate every input by invoking the `ome-zarr-models validate` CLI as a subprocess gate before any
processing; fail fast with the CLI's message on non-zero exit. Read the multiscale group to
enumerate levels and their `coordinateTransformations`; access the selected level's array lazily and
stream slices.

**Rationale**: OME-Zarr v0.5 is defined on top of Zarr format 3, which `zarr>=3` reads/writes
natively with no extra dependency. `ome-zarr-models` is the user-mandated validator and also
provides typed access to multiscale metadata, so we reuse it instead of re-parsing JSON. Shelling
out to its CLI exactly matches the user's instruction and keeps validation authoritative and
version-aligned with whatever `ome-zarr-models` is installed.

**Alternatives considered**:
- `ome-zarr-py` (`ome_zarr`): broader reader/writer but heavier and historically v0.4-centric; not
  needed when `zarr` v3 + `ome-zarr-models` cover v0.5.
- Calling the validator programmatically: workable, but the user explicitly asked for the
  `ome-zarr-models validate` CLI command, so subprocess invocation is the contract.

## R2. SAM2 video predictor integration and "creating a video of every slice"

**Decision**: Treat each axis sweep as a video whose frames are the volume's 2D slices along that
axis. Drive SAM2 through its video predictor API (`build_sam2_video_predictor` ->
`init_state` -> `add_new_points_or_box(frame_idx, obj_id, points, labels, box)` ->
`propagate_in_video(...)`, plus `propagate_in_video(reverse=True)` for the reverse pass). Wrap this
behind a `VideoSegmenterBackend` protocol so SAM3 implements the same shape.

**Rationale**: SAM2's video predictor is purpose-built to propagate a mask across an ordered frame
sequence from sparse prompts on one or more frames, which is exactly the slice-propagation behavior
the spec describes. Forward-only vs forward-and-reverse (FR-006) maps directly onto running
`propagate_in_video` once or in both directions and merging.

**Alternatives considered**:
- SAM (v1) image predictor per slice with no temporal link: loses inter-slice coherence, much worse
  propagation. Rejected.
- Custom tracking between independent per-slice SAM calls: reinvents SAM2's video propagation.
  Rejected.

## R3. Intermediate storage: how to write the "video" and store intermediate results

**Decision**:
- **Frames**: normalize each selected-level slice to uint8, broadcast to 3 channels (SAM expects
  RGB), and store the frame stack for a sweep in an on-disk **NumPy memmap**. Feed SAM2 from this
  store; when the installed SAM2 build requires a JPEG frame directory, materialize frames from the
  memmap lazily into a temp dir, otherwise pass arrays directly.
- **Per-sweep masks**: do not retain every sweep in memory. Maintain a single on-disk **memmap vote
  accumulator** (uint8/uint16, shaped like the level volume); each completed sweep increments voxels
  it marked foreground. The consensus mask is `votes > (n_sweeps / 2)`.
- Intermediates live under a temp working directory and are removed on success.

**Rationale**: Volumes are larger than RAM, so intermediates must be out-of-core; memmap gives
lossless, random-access, depth-independent RAM usage (meets the Principle IV target). memmap is
preferred over JPEG frames because JPEG is lossy and degrades SAM input quality, and over an
intermediate OME-Zarr because Zarr's chunking/metadata overhead is unnecessary for transient,
densely-scanned data. The vote accumulator makes majority-vote combination (the clarified default)
streaming and memory-bounded regardless of how many axes/directions are swept.

**Alternatives considered**:
- JPEG frame directory (SAM2 default tutorial path): lossy; rejected for fidelity. Still supported
  as the fallback feed mechanism only.
- Intermediate OME-Zarr for frames/sweeps: more metadata/IO overhead, no benefit for transient data.
- All-in-RAM: violates the depth-independent RAM target on large volumes.

## R4. SAM2 prompt-encoder compatibility (single point / box / exclusion point)

**Decision**: Represent prompts exactly as SAM2's prompt encoder expects and pass them through
unchanged:
- Point coordinates: array shape `(N, 2)` in `(x, y)` pixel coordinates of the slice/frame.
- Point labels: array shape `(N,)`, `1` = positive (include), `0` = negative (exclude). Box corners
  are encoded by SAM2 internally as labels `2` (top-left) and `3` (bottom-right); padding is `-1`.
- Box: `(4,)` `[x_min, y_min, x_max, y_max]`, passed to `add_new_points_or_box` (we do not hand-encode
  corner labels; SAM2 does that).
- Each prompt is attached to a specific frame index (the slice it was placed on) and object id.

This maps the three first-to-test features directly:
1. **Single-point input** -> one point, label `1`.
2. **Bounding-box input** -> `box=[x0,y0,x1,y1]` (optionally with points).
3. **Exclusion-point input** -> an additional point with label `0` alongside positive prompts.

**Rationale**: Matching the prompt encoder's `(coords, labels, box)` convention verbatim guarantees
backend compatibility (the user's explicit ask referencing `prompt_encoder.py`) and makes the public
API a thin, faithful mirror of the SAM API (FR-010, SC-004). The label semantics (1/0, box 2/3,
pad -1) are the encoder's reserved point-embedding indices, so adopting them avoids any translation
layer.

**Alternatives considered**:
- A bespoke prompt schema translated into SAM calls: adds surface area and drift risk; rejected in
  favor of the native convention.

## R5. Output multiscale pyramid matching the input levels

**Decision**: Compute the mask at the selected level, then build an output OME-Zarr v0.5 whose
multiscale group has the **same number of levels** as the input, reusing the input's per-level
shapes and `coordinateTransformations`. Resample the computed mask to each level's grid with
**nearest-neighbor** (label-preserving): downsample for coarser levels, and for levels finer than
the run level, upsample by nearest-neighbor so the foreground aligns. Write masks as an integer
label dtype.

**Rationale**: The user requires the final OME-Zarr to have the same levels as the input, and the
mask must register against the input (SC-002), so copying the input's level geometry/metadata is the
faithful approach. Nearest-neighbor is the correct resampling for categorical masks (no
interpolation across label boundaries).

**Default level**: when `--level` is omitted, use the coarsest level (highest index). It gives the
fastest first result, matches the "coarse level for a fast preview" intent, and makes the
coarser-is-faster outcome (SC-006) easy to demonstrate.

**Alternatives considered**:
- Single-level output: violates the explicit "same levels as input" requirement.
- Linear/area downsampling: produces fractional values meaningless for labels; rejected.

## R6. Backend selection and model-weight management

**Decision**: A `backends/registry.py` resolves a backend by name; **sam2** is the default, **sam3**
selectable, both first-class behind the `VideoSegmenterBackend` protocol. Model weights resolve from
a model directory defaulting to a subdirectory of the **current working directory**
(`./ome_zarr_masker_models/` by default), overridable by CLI option and environment variable. Missing
weights are **auto-downloaded** into that directory on first use; a `--no-download` opt-out disables
this and yields a clear error when weights are absent. The default model directory is added to the
project `.gitignore`.

**Rationale**: Directly encodes the clarified answers (both backends first-class, SAM2 default,
auto-download with opt-out, working-dir subdirectory). Gitignoring the default location prevents
large weights from being committed (Principle III: no generated artifacts committed).

**Alternatives considered**: covered in the clarifications session; not re-litigated here.

## R7. CLI and interactive technology (minimal deps)

**Decision**: One-shot CLI uses stdlib `argparse` (no third-party CLI dependency). Interactive mode
(P4) uses `napari` provided through the `[interactive]` extra; it calls the same engine/predictor.

**Rationale**: "Minimal deps" rules out click/typer for the core. napari is the de-facto n-dimensional
image viewer in this scientific-imaging domain and matches the reference project's interaction model;
isolating it as an extra keeps the core lightweight.

**Alternatives considered**: click/typer (extra dependency for no required capability); a custom GUI
(far more work than napari). Both rejected.

## R8. Post-processing defaults

**Decision**: Post-processing is opt-in-shaped with conservative defaults: fill-holes **enabled** by
default; dilation/erosion **disabled** by default (radius 0). All are independently controllable and
fully skippable (FR-012). Implemented with `scipy.ndimage` (`binary_dilation`, `binary_erosion`,
`binary_fill_holes`).

**Rationale**: Filling interior holes almost always improves a 3D organ mask without changing extent,
satisfying SC-007, while morphological open/close that changes the boundary should be a deliberate
user choice. SciPy provides correct, fast, n-dimensional implementations.

**Alternatives considered**: aggressive default morphology (risks eroding thin structures); custom
morphology (unjustified given SciPy). Both rejected.

## Resolved unknowns

All Technical Context items are resolved; no `NEEDS CLARIFICATION` markers remain. Exact pinned
weight checkpoints per backend and final benchmark numbers are implementation details to be set and
measured during implementation, within the performance targets stated in the plan.
