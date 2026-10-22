# Feature Specification: OME-Zarr Organ Masking with SAM

**Feature Branch**: `001-ome-zarr-sam-masking`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Create a Python package based on https://github.com/HiPCTProject/organ-masker but with best practices, focusing on adding functionalities step by step. ome-zarr-masker accepts an ome-zarr v0.5 image as input and creates an ome-zarr v0.5 mask as final output. it uses sam as a backend, by creating a video of every slice in forward-only or forward and reverse modes, combining outputs from each axis. it features an interactive mode and a cli one-shot mode, along with an api to input landmark locations to sam (this api has to be straightforward to use, by making it similar in structure to the sam api). it has to leverage the different binning levels within an ome-zarr, so that the user can pick which level to use. postprocessing of the mask such as dilation/erosion or fill-holes are optional, with sensible default values"

## Overview

ome-zarr-masker produces a 3D segmentation mask of an organ (or other structure) from a
large volumetric image, using a foundation segmentation model (SAM-family) guided by a small
set of user-placed landmarks. The volume is processed as stacks of 2D slices: each axis is
swept slice-by-slice so the model can propagate a segmentation from the landmark slices through
the volume, and the per-axis results are combined into a single consensus mask. Input and output
are both OME-Zarr v0.5, and the user chooses which resolution (binning) level of the multiscale
pyramid to operate on. Optional morphological post-processing cleans up the result.

The product is delivered as a Python package offering three entry points that share one core
engine: a one-shot command-line workflow, an interactive workflow for placing and refining
landmarks visually, and a programmatic API whose shape mirrors the familiar SAM prediction API.
Functionality is built up incrementally, with each user story below a self-contained increment.

## Clarifications

### Session 2026-06-14

- Q: Is SAM3 a first-class, user-selectable backend in v1, or comparison-only? → A: Both SAM2 and SAM3 are first-class, fully supported and tested backends (SAM2 remains the default selection when none is specified, per the original request).
- Q: How should the tool obtain model weights when missing from the model directory? → A: Auto-download missing weights into the model directory by default, with an opt-out flag (clear error when disabled/offline and weights are missing).
- Q: Where should the default local model directory live (overridable)? → A: A subdirectory of the current working directory, overridable via an explicit option/environment variable.
- Q: Default rule for combining per-sweep masks into the consensus mask? → A: Per-voxel majority vote.
- Q: Output cardinality — single binary mask or multi-object label map? → A: Single binary foreground mask (0/1), one target structure per run; segmenting multiple distinct objects in one run is out of scope (use separate runs).
- Q: How do prompts placed on one plane drive multi-axis sweeps? → A: Seed from the prompted axis — propagate the prompted axis first to a 3D mask, then automatically derive per-slice seeds for the other axes' sweeps.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One-shot masking from landmarks via CLI (Priority: P1)

A researcher has an OME-Zarr v0.5 volume and knows roughly where the target organ sits. They
provide a small set of landmark prompts (points labelled as inside/outside the organ, optionally
a bounding box) in a prompt file and run a single command. The tool sweeps the volume slice-by-
slice along one axis, propagates the segmentation from the landmark slices through the stack, and
writes an OME-Zarr v0.5 mask aligned to the chosen input level.

**Why this priority**: This is the minimum end-to-end value: image in, mask out, no manual
babysitting. Every other story builds on this core pipeline.

**Independent Test**: Run the one-shot command on a sample OME-Zarr volume with a fixed prompt
file and confirm it produces a valid OME-Zarr v0.5 mask whose foreground overlaps the target
structure, with no interactive steps required.

**Acceptance Scenarios**:

1. **Given** a valid OME-Zarr v0.5 input and a prompt file with at least one positive point,
   **When** the user runs the one-shot command, **Then** an OME-Zarr v0.5 mask is written to the
   requested output location with the same voxel grid as the selected input level.
2. **Given** a prompt file containing both positive and negative points, **When** the command
   runs, **Then** negative points are excluded from the foreground of the resulting mask.
3. **Given** an output path that already exists, **When** the command runs without an overwrite
   flag, **Then** the tool refuses to overwrite and reports a clear error.
4. **Given** an input that is not a readable OME-Zarr v0.5 store, **When** the command runs,
   **Then** the tool exits with a non-zero status and a clear, actionable message.

---

### User Story 2 - Multi-axis sweeps and bidirectional propagation (Priority: P2)

The user wants higher-quality masks than a single-axis sweep gives. They request that the volume
be swept along more than one axis and that propagation run either forward-only or forward-and-
reverse, with the per-sweep results combined into one consensus mask.

**Why this priority**: Combining independent sweeps materially improves mask completeness and
robustness over the P1 single-axis pass, but it is an enhancement of an already-working pipeline.

**Independent Test**: On a sample volume, run a multi-axis forward-and-reverse pass and a single-
axis forward-only pass with identical prompts, and confirm the multi-axis consensus mask has
equal or greater agreement with the reference segmentation than the single-axis result.

The user places landmarks on a single plane; the prompted axis is swept first, and the other
selected axes are seeded automatically from that 3D result rather than requiring new prompts.

**Acceptance Scenarios**:

1. **Given** a chosen set of axes to sweep, **When** masking runs, **Then** the prompted axis is
   swept first, the other selected axes are seeded from its 3D mask and swept, and all per-sweep
   outputs are merged by the configured combination rule into one mask.
2. **Given** forward-and-reverse mode, **When** masking runs along an axis, **Then** the structure
   is propagated in both directions from the landmark slices and the two directions are merged.
3. **Given** no combination rule is specified, **When** multiple sweeps run, **Then** a documented
   default combination rule is applied and recorded in the run output.

---

### User Story 3 - Choosing the resolution (binning) level (Priority: P2)

The user wants to control the speed/detail trade-off by selecting which level of the OME-Zarr
multiscale pyramid to run on (e.g., a coarse level for a fast preview, a finer level for the final
mask).

**Why this priority**: OME-Zarr inputs are large; the ability to pick a level is essential for
practical runtimes and iteration, but it is a parameter on top of the core pipeline.

**Independent Test**: Run the same prompts against two different pyramid levels of one input and
confirm each run produces a mask matching the voxel grid of the level it was run on, and that the
coarser level completes faster.

**Acceptance Scenarios**:

1. **Given** an OME-Zarr input with several pyramid levels, **When** the user selects a level,
   **Then** masking runs on that level and the output mask matches that level's voxel grid.
2. **Given** a requested level that does not exist in the input, **When** the run starts, **Then**
   the tool reports the available levels and exits without producing a partial mask.
3. **Given** no level is specified, **When** a run starts, **Then** a documented default level is
   selected and reported.

---

### User Story 4 - Programmatic landmark API mirroring SAM (Priority: P3)

A developer wants to drive masking from their own Python code, supplying landmark prompts
programmatically. The API mirrors the structure of the SAM prediction API (set an image/volume,
then predict from point coordinates, point labels, and/or a box) so that anyone familiar with SAM
can use it with minimal learning.

**Why this priority**: The API unlocks scripting, batch use, and integration, and it is the
foundation the interactive mode also builds on, but the CLI already delivers standalone value.

**Independent Test**: From a short Python script (a handful of lines), load a volume, pass point
coordinates and labels in the SAM-style signature, and obtain a mask object equivalent to the CLI
output for the same prompts.

**Acceptance Scenarios**:

1. **Given** a loaded volume, **When** the developer calls the predict entry point with point
   coordinates and point labels, **Then** a mask is returned for those prompts.
2. **Given** the same prompts, **When** invoked through the API and through the CLI, **Then** both
   produce equivalent masks.
3. **Given** a developer familiar with the SAM prediction API, **When** they read the method
   signatures, **Then** prompt arguments (point coordinates, point labels, box) follow the same
   naming and shape conventions as SAM.

---

### User Story 5 - Optional mask post-processing (Priority: P3)

The user can optionally clean up the produced mask with morphological operations (dilation,
erosion) and hole filling. These are off or set to sensible defaults unless the user adjusts them.

**Why this priority**: Post-processing improves usability of the final mask but is a refinement;
the core mask is already valuable without it.

**Independent Test**: Run masking with post-processing disabled and with default post-processing
on the same volume, and confirm the post-processed mask has fewer interior holes while remaining
a valid OME-Zarr v0.5 mask.

**Acceptance Scenarios**:

1. **Given** post-processing is left at defaults, **When** masking completes, **Then** the
   documented default operations are applied and the choices are recorded in the run output.
2. **Given** the user disables post-processing, **When** masking completes, **Then** the raw
   consensus mask is written unchanged.
3. **Given** the user sets dilation/erosion amounts or toggles fill-holes, **When** masking
   completes, **Then** the output reflects exactly those operations.

---

### User Story 6 - Interactive masking session (Priority: P4)

The user opens an interactive session to view slices of the volume, place and adjust landmarks
visually, preview the resulting mask, and iterate before exporting the final OME-Zarr v0.5 mask.

**Why this priority**: Interactive refinement is the most powerful workflow for hard cases, but it
depends on the core engine and the programmatic API, so it comes last as an increment.

**Independent Test**: Launch the interactive session on a sample volume, place a positive and a
negative landmark, trigger a preview, observe the mask update, and export a valid OME-Zarr v0.5
mask.

**Acceptance Scenarios**:

1. **Given** an open interactive session, **When** the user places a positive landmark and
   requests a preview, **Then** a mask preview is shown for the current prompts.
2. **Given** an existing preview, **When** the user adds a negative landmark and re-previews,
   **Then** the preview updates to exclude that region.
3. **Given** a satisfactory preview, **When** the user exports, **Then** an OME-Zarr v0.5 mask is
   written using the same engine and combination settings as the one-shot workflow.

---

### Edge Cases

- What happens when the prompt file contains no positive points (only negatives or empty)? The
  run is rejected with a clear message rather than producing an empty mask silently.
- How does the system handle landmark coordinates that fall outside the bounds of the selected
  level, or that are expressed at a different level than the run level?
- What happens when the target structure is absent from a slice during propagation (the structure
  ends partway through the volume)?
- What happens when the prompted-axis sweep yields no foreground to seed the other axes? The run
  reports an empty/failed segmentation clearly rather than silently producing an empty mask.
- How does the system behave when the selected level, or the intermediate frame/vote stores, do not
  fit in available memory or disk? The run must fail with a clear, actionable error (a preflight
  size/disk check) rather than crash unpredictably.
- How are anisotropic voxels (different physical spacing per axis) handled when combining sweeps
  from different axes?
- What happens when sweeps from different axes disagree strongly on a region (combination rule
  tie-breaking)?
- How does the system handle an interrupted run (partial output must not be mistaken for a
  complete mask)?
- How does the output mask record the metadata (coordinate transforms, axis order) needed for it
  to register correctly against the input level?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept an OME-Zarr v0.5 store as input and validate that it is readable
  and conforms to the expected multiscale structure before processing.
- **FR-002**: System MUST write the final mask as an OME-Zarr v0.5 store whose voxel grid and
  spatial metadata align with the selected input resolution level.
- **FR-003**: System MUST let the user select which resolution (binning) level of the input
  multiscale pyramid to operate on, and MUST report the levels available when an invalid level is
  requested.
- **FR-004**: System MUST accept landmark prompts consisting of point coordinates with labels
  (inside/outside the target) and MUST support an optional bounding box prompt.
- **FR-005**: System MUST generate the mask by sweeping the volume as ordered 2D slices and
  propagating the segmentation from landmark slices through the stack using the SAM-family backend.
- **FR-006**: System MUST support propagation in forward-only and forward-and-reverse modes,
  user-selectable per run.
- **FR-007**: System MUST support sweeping along one or more user-selected axes and MUST combine
  the per-sweep results into a single mask using a configurable combination rule; the default rule
  is a per-voxel majority vote.
- **FR-008**: System MUST provide a one-shot command-line workflow that runs end-to-end from input
  plus prompt file to output mask without interactive input.
- **FR-009**: System MUST provide an interactive workflow for viewing slices, placing/adjusting
  landmarks, previewing the resulting mask, and exporting the final mask.
- **FR-010**: System MUST provide a programmatic API for supplying landmark prompts whose method
  names and argument shapes mirror the SAM prediction API (point coordinates, point labels, box),
  so SAM users can adopt it with minimal learning.
- **FR-011**: All three entry points (CLI, interactive, API) MUST share a single masking engine so
  that identical inputs and prompts produce equivalent masks.
- **FR-012**: System MUST offer optional post-processing of the mask, including dilation, erosion,
  and hole filling, each independently controllable, applied with sensible documented defaults and
  fully skippable.
- **FR-013**: System MUST refuse to overwrite an existing output unless the user explicitly opts in,
  and MUST never leave a partial output that is indistinguishable from a complete mask.
- **FR-014**: System MUST record, alongside each output, the run parameters used (selected level,
  axes, propagation mode, combination rule, post-processing settings, and prompts) for
  reproducibility.
- **FR-015**: System MUST validate prompts (at least one positive point, coordinates within the
  selected level's bounds) and reject runs that cannot produce a meaningful mask with a clear error.
- **FR-016**: System MUST handle inputs too large to fit in memory at the selected level without
  unpredictable failure (e.g., by processing in chunks or by failing with clear guidance).
- **FR-017**: System MUST report progress for long-running operations so the user can gauge
  remaining work.
- **FR-018**: System MUST support SAM2 and SAM3 as first-class, fully supported and tested
  segmentation backends, selectable by the user through both the CLI and the API; SAM2 is used as
  the default backend when the user does not specify one.
- **FR-019**: System MUST resolve model weights from a configurable local model directory that
  defaults to a subdirectory of the current working directory and is overridable via an explicit
  option and/or environment variable.
- **FR-020**: System MUST, when required model weights are absent from the model directory,
  download them into that directory by default, and MUST provide an opt-out that disables
  downloading; when downloading is disabled or unavailable (e.g., offline) and the weights are
  missing, the system MUST fail with a clear, actionable message.
- **FR-021**: System MUST produce a single binary foreground mask (values 0/1) for one target
  structure per run. Segmenting multiple distinct objects in a single run is out of scope; multiple
  structures are obtained via separate runs.
- **FR-022**: For multi-axis sweeps, the System MUST seed the non-prompted axes automatically from
  the 3D mask produced by the prompted axis: it propagates the prompted axis first, then derives
  per-slice seeds for each other selected axis from that result (the user places landmarks on a
  single plane only).

### Key Entities *(include if feature involves data)*

- **Input Volume**: An OME-Zarr v0.5 multiscale image; key attributes are its resolution levels,
  per-axis sizes, axis order, and spatial metadata (voxel spacing/transforms).
- **Resolution Level**: One scale of the input pyramid; the unit of selection that determines run
  speed, detail, and the output mask's voxel grid.
- **Landmark Prompt**: A point with an inside/outside label, or an optional bounding box, expressed
  in the coordinate space of the selected level; the guidance given to the segmentation backend.
- **Sweep**: One traversal of the volume as ordered slices along a chosen axis in a chosen
  direction; produces a per-sweep mask candidate. The prompted (primary) sweep uses the user's
  landmarks; seeded sweeps along other axes derive their per-slice seeds from the prompted axis's
  3D result.
- **Consensus Mask**: The single binary foreground mask formed by combining the per-sweep
  candidates by the combination rule.
- **Output Mask**: An OME-Zarr v0.5 store representing the final (optionally post-processed) single
  binary foreground mask (0/1) aligned to the selected input level.
- **Run Configuration**: The full set of parameters for a run (selected backend, level, axes,
  propagation mode, combination rule, post-processing settings, prompts) recorded for
  reproducibility.
- **Backend**: The segmentation model used for a run, either SAM2 (default) or SAM3; determines
  which model weights are resolved from the model directory.
- **Model Directory**: The local location where model weights are stored, defaulting to a
  subdirectory of the current working directory and overridable; missing weights may be
  auto-downloaded here.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from an OME-Zarr v0.5 input plus a prompt file to a written OME-Zarr
  v0.5 mask in a single command with no interactive steps.
- **SC-002**: The output mask is readable as valid OME-Zarr v0.5 by standard OME-Zarr tooling and
  registers correctly against the input level (same voxel grid and spatial metadata).
- **SC-003**: On a reference volume with a known segmentation, a multi-axis forward-and-reverse run
  achieves mask agreement (overlap with the reference) at least as high as a single-axis forward-
  only run with the same prompts.
- **SC-004**: A developer can produce a mask programmatically in 5 or fewer lines of code, and
  users familiar with the SAM prediction API can do so without consulting documentation beyond the
  method signatures.
- **SC-005**: The CLI and API produce equivalent masks for identical inputs and prompts.
- **SC-006**: Selecting a coarser resolution level reduces end-to-end run time relative to a finer
  level on the same input.
- **SC-007**: Enabling default post-processing reduces the number of interior holes in the mask
  compared with the raw consensus mask on a reference volume.
- **SC-008**: Every produced mask is accompanied by a record of the run parameters sufficient to
  reproduce it.
- **SC-009**: Invalid inputs (bad store, missing level, no positive prompt, out-of-bounds prompt)
  are rejected with a clear, actionable message and a non-zero exit status, with no partial output
  left behind.
- **SC-010**: A user can run the same input and prompts through both the SAM2 and SAM3 backends by
  changing only the backend selection, enabling a like-for-like comparison of their masks.
- **SC-011**: On a machine with no pre-downloaded weights and network access, a first run obtains
  the required weights automatically; with the download opt-out enabled and weights missing, the
  run fails with a clear message instead of attempting a download.

## Assumptions

- The segmentation backend is a SAM-family model capable of propagating a segmentation across an
  ordered sequence of slices (treating each axis sweep as a "video" of slices). Both SAM2 and SAM3
  are first-class, fully supported and tested backends; SAM2 is the default when none is specified.
  The exact model weights/checkpoints per backend are finalized in planning.
- "Combining outputs from each axis" defaults to a per-voxel majority vote across sweeps;
  alternative rules (e.g., union, intersection) remain configurable. The default and the chosen
  rule are documented and recorded per run.
- Model weights live in a configurable local model directory defaulting to a subdirectory of the
  current working directory; missing weights are auto-downloaded there by default, with an opt-out.
  Because the default lives in the working directory, the model subdirectory should be excluded
  from version control (handled in planning/implementation).
- The default resolution level when none is specified is a coarse pyramid level suitable for a fast
  first result; the exact default is finalized in planning.
- Default post-processing values are conservative (small or no morphological change, hole filling
  enabled) and chosen so the default does not degrade a reasonable mask; exact values finalized in
  planning.
- Landmark coordinates are expressed in the coordinate space of the selected resolution level
  unless a level is explicitly associated with them.
- The interactive mode targets a single user on a workstation with access to the input store; it is
  not a multi-user or remote-hosted service in this feature.
- Inputs may be larger than memory at fine levels; chunked/lazy access to the OME-Zarr store is
  expected rather than loading whole volumes eagerly.
- Performance targets (acceptable run time and memory ceiling for a defined reference volume and
  level) will be set explicitly in the plan per the project constitution's Performance Requirements
  principle; this spec asserts only relative outcomes (SC-006).
- The package is built incrementally following the prioritized user stories, with US1 as the
  initial shippable increment.
- Each run targets a single structure and produces a single binary foreground mask; multi-object
  (multi-label) segmentation is out of scope for this feature (object identifiers, if present, are
  an internal single-object detail).
- In multi-axis runs the user places landmarks on one plane only; the non-prompted axes are seeded
  automatically from the prompted axis's 3D result rather than requiring per-axis prompts.

## Dependencies

- Availability of the SAM2 and SAM3 segmentation backends (models and weights) and the compute
  (CPU/GPU) appropriate to run them. Weights are obtained by auto-download into the local model
  directory by default, which requires network access on first use unless the opt-out is used and
  weights are pre-placed.
- The OME-Zarr v0.5 specification for both reading inputs and writing outputs.
- The reference behavior of the existing HiPCTProject/organ-masker project as functional
  inspiration (ome-zarr-masker is a clean reimplementation, not a fork constrained by its code).
