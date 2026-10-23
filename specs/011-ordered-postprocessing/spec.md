# Feature Specification: Ordered Post-Processing Pipeline

**Feature Branch**: `011-ordered-postprocessing`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "Ordered post-processing pipeline (feature 011). Replace the fixed post-processing options (--fill-holes/--no-fill-holes, --dilate, --erode, --invert, applied in a hard-coded order: dilate, erode, fill-holes, invert) with an explicit, ordered sequence of steps, given either on the command line (e.g. `--postprocess close:3,fill,largest,margin:200um,invert`) or in a separate post-processing file (e.g. `--postprocess-file steps.json`), never in the prompt file; the two are mutually exclusive. No backward compatibility: the old flags and the old PostProcessConfig fields are removed. Steps: fill, close:r, open:r, dilate:r, erode:r, largest, margin:r, invert. Radii are either run-level voxels (bare number) or physical lengths with a unit (e.g. 200um, 0.2mm), converted with the run level's per-axis scale and the axes' units from the OME-Zarr metadata; a physical radius on axes without units is rejected. Morphology uses a ball (ellipsoid in voxels for physical radii). Default when nothing is given: fill only. Invalid steps, radii or units fail before any segmentation. The same sequence is accepted by the Python API and by the interactive subcommand, and is recorded in run_record.json and the input log. Motivation: user feedback on masking a 7526x6985x6985 HiP-CT volume (DANDI 001278). Also document in the README that prompting several planes reduces sweep dropouts."

## Clarifications

### Session 2026-10-23

- Q: With `interactive --postprocess ...`, where are the steps saved? → A: Both as the session's
  defaults (pre-filled in a napari post-processing panel, where the user can change them) and with
  the prompts: the final values in the panel are saved into the prompt file together with the
  prompts. This replaces the earlier "never in the prompt file" rule.
- Q: What does the keyword `default` mean? → A: It is the default value of `--postprocess`:
  inherit the steps saved with the prompts if there are any, otherwise apply no steps. Hole filling
  is therefore no longer applied unless `fill` is listed (explicitly or in the inherited steps).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Clean up a mask with an ordered sequence of steps (Priority: P1)

A researcher masking a large HiP-CT volume with a multi-axis majority run gets thin planes of
missing voxels where one sweep briefly lost the sample, small detached fragments, and a mask that
hugs the sample too tightly. Today they export the raw mask and clean it with their own script
(closing, fill holes, keep the largest component, then a safety margin), because the tool's fixed
order (dilate, erode, fill holes, invert) cannot express that. With this feature they write the
steps in the order they want on the command line, e.g. `--postprocess close:3,fill,largest,margin:3`,
and get the finished mask from a single run.

**Why this priority**: It removes the external clean-up script that every large run currently
needs, and it is the change every other story builds on.

**Independent Test**: Run `mask` with a post-processing sequence on a synthetic volume whose raw
mask has a one-voxel gap plane, an interior hole and a detached fragment; the output equals the
same steps applied by hand, in that order, to the raw mask.

**Acceptance Scenarios**:

1. **Given** a run whose raw mask has a thin gap plane, a hole and a small detached fragment,
   **When** the user runs `mask ... --postprocess close:3,fill,largest,margin:3`, **Then** the output
   has the gap closed, the hole filled, only the largest component kept, and a 3-voxel margin
   added, applied in exactly that order.
2. **Given** the same raw mask, **When** the user gives the same steps in a different order (e.g.
   `margin:3,largest,fill,close:3`), **Then** the result is the steps applied in that new order,
   which may differ from scenario 1.
3. **Given** no post-processing option (equivalently `--postprocess default`) and a prompt file
   without saved steps, **When** the user runs `mask`, **Then** the raw consensus mask is written
   unchanged (hole filling is not applied unless `fill` is listed).
4. **Given** a prompt file with saved steps and `--postprocess none`, **When** the user runs `mask`,
   **Then** no steps are applied: `none` overrides the saved steps.
5. **Given** a sequence ending in `invert`, **When** the user runs `mask`, **Then** the written mask
   is the complement of the mask produced by the steps before it; steps placed after an `invert` act
   on the inverted mask.
6. **Given** a sequence with an unknown step, a missing or non-positive radius, or a radius on a
   step that takes none, **When** the user runs `mask`, **Then** it fails before any segmentation
   with a message naming the offending step and the accepted steps.

---

### User Story 2 - Give radii as physical sizes (Priority: P2)

The same researcher tunes the margin and closing on a coarse level, then reruns on a finer level.
A radius in voxels means a different physical size at each level, so they give radii in physical
units instead (`margin:200um`, `close:0.2mm`); the tool converts them using the run level's voxel
size along each axis, so the same command gives the same physical clean-up at any level, and stays
correct when voxels are not cubic.

**Why this priority**: Without it, every change of level silently changes the clean-up; it matters
as soon as users move between levels, but bare voxel radii already deliver User Story 1.

**Independent Test**: Run the same sequence with a physical radius at two levels of a test pyramid
and compare the masks at a common level: the added margin has the same physical thickness to
within one run-level voxel.

**Acceptance Scenarios**:

1. **Given** a store whose axes declare a length unit, **When** the user runs at level 1 and at
   level 3 with `--postprocess margin:200um`, **Then** the margin is about 200 µm thick in both runs
   (within one run-level voxel along each axis).
2. **Given** a level whose voxels are larger along one axis, **When** the user gives a physical
   radius, **Then** the structuring shape is an ellipsoid in voxels that is a sphere of that radius
   in physical space.
3. **Given** a store whose axes declare no unit, **When** the user gives a physical radius, **Then**
   it fails before segmentation with a message saying the store has no axis units and that a radius
   in voxels can be used instead.
4. **Given** a physical radius that is smaller than one voxel along every axis at the run level,
   **When** the user runs `mask`, **Then** it fails before segmentation with a message giving the
   run level's voxel size.
5. **Given** an unknown unit (e.g. `200furlong`), **When** the user runs `mask`, **Then** it fails
   before segmentation with a message listing the accepted units.

---

### User Story 3 - Choose the steps interactively and keep them with the prompts (Priority: P3)

A user places prompts in the interactive session and tunes the clean-up while looking at the
preview. They start the session with `interactive IN --prompts p.json --postprocess close:3,fill`;
those steps are pre-filled in a post-processing panel, where they adjust them (say, adding
`largest,margin:200um`) and re-preview. When they save, the prompt file holds the prompts and the
final steps, so `mask IN OUT --prompts p.json` applies exactly that clean-up without repeating it.

**Why this priority**: It closes the loop between tuning and batch runs, but needs the sequence
(US1) and benefits from physical radii (US2).

**Independent Test**: Start a session with `--postprocess`, change the steps in the panel (or
through the session's programmatic interface), save the prompts, then run `mask` with that prompt
file and no `--postprocess`: the output equals the session's export with the final steps.

**Acceptance Scenarios**:

1. **Given** `interactive IN --prompts p.json --postprocess close:3,fill`, **When** the session
   opens, **Then** the post-processing panel shows `close:3,fill` and previews and exports use it.
2. **Given** an open session, **When** the user edits the steps in the panel, **Then** later
   previews and exports use the edited steps; an invalid edit is refused with the same message as
   on the command line and the previous steps stay in effect.
3. **Given** the user saves the prompts, **When** the prompt file is written, **Then** it contains
   the prompts and the steps currently in the panel (the final values, not the command-line ones).
4. **Given** a prompt file with saved steps, **When** the user runs `mask` with it and no
   `--postprocess` (or `--postprocess default`), **Then** the saved steps are applied; with an
   explicit `--postprocess` or `--postprocess-file`, those are applied instead.
5. **Given** `interactive IN --prompts p.json` where `p.json` already has prompts and saved steps,
   **When** the session opens with no `--postprocess`, **Then** the prompts are loaded and the panel
   shows the saved steps.
6. **Given** no saved steps and no `--postprocess`, **When** the session opens, **Then** the panel
   is empty (no steps).

---

### User Story 4 - Reuse one sequence everywhere and reproduce it (Priority: P4)

A lab keeps a standard clean-up for a sample type in a small post-processing file and uses it
from the command line, the Python API and the interactive session. Later they reproduce any run
from its run record, which lists the steps that were applied and where they came from.

**Why this priority**: Sharing and reproducibility build on the sequence itself; useful for
routine use, not needed for a first clean run.

**Independent Test**: Run the same sequence given on the command line, in a post-processing file,
saved in the prompt file, through the Python API and through an interactive export on the same
input and prompts: all masks are identical, and rerunning from the steps listed in the run record
gives the same mask.

**Acceptance Scenarios**:

1. **Given** a post-processing file containing a sequence, **When** the user runs
   `mask ... --postprocess-file steps.json`, **Then** the result is identical to giving the same
   sequence with `--postprocess`.
2. **Given** both `--postprocess` and `--postprocess-file`, **When** the user runs `mask` or
   `interactive`, **Then** it fails before segmentation with a message that only one may be given.
3. **Given** a sequence, **When** the user passes it to the Python API's predict and to the
   interactive session's preview and export, **Then** the masks are identical to the CLI's.
4. **Given** a completed run, **When** the user reads its run record and input log, **Then** both
   list the applied steps in order, with each radius as given and as resolved in voxels per axis,
   and where the steps came from (command line, post-processing file, prompt file, or none);
   rerunning with those steps reproduces the mask exactly.

---

### Edge Cases

- An empty raw mask: every step runs without error; `largest` on an empty mask leaves it empty;
  `invert` of an empty mask is all foreground.
- `largest` when two components have exactly the same size: the result is deterministic (the same
  component is kept every run) and documented.
- `default` combined with other steps (e.g. `default,margin:3`) is rejected: `default` and `none`
  must appear alone.
- A prompt file whose saved steps are invalid fails before segmentation with a message naming the
  prompt file and the step, as for any other source.
- Saving prompts when the panel holds no steps writes the prompt file without saved steps (so
  `default` then means no steps).
- A step repeated several times (e.g. `fill,close:2,fill`) is applied each time it appears.
- More than one `invert` is allowed; each one complements the current mask.
- Radii given with decimals (`1.5`, `0.15mm`) are accepted; radius `0` or negative is rejected.
- A large radius (relative to the volume) still completes and does not wrap around the volume
  edges: for `dilate`, `erode`, `margin` and `open`, everything outside the volume counts as
  background; `close` never removes a mask voxel, so a sample touching the volume edge is not
  eroded there.
- Whitespace around commas and step names in the command-line form is ignored; step names and
  units are case-insensitive (`um`, `µm`, `UM`).
- A post-processing file that is missing, unreadable or malformed fails before segmentation with
  a message naming the file.
- The removed options (`--fill-holes`, `--no-fill-holes`, `--dilate`, `--erode`, `--invert`) are no
  longer accepted; using one is a usage error that points to `--postprocess`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `mask` and `interactive` MUST accept a post-processing sequence either on the command
  line (`--postprocess STEPS`, steps separated by commas) or from a post-processing file
  (`--postprocess-file FILE`), but not both. The default value of `--postprocess` is the keyword
  `default`.
- **FR-002**: The supported steps MUST be: `fill` (fill holes), `close:R`, `open:R`, `dilate:R`,
  `erode:R`, `largest` (keep the largest connected component), `margin:R` (add every voxel within
  distance R of the mask) and `invert` (swap mask and background). Two keywords stand alone:
  `default` (inherit the steps saved in the prompt file, or no steps if there are none) and `none`
  (no steps, even if the prompt file has saved steps).
- **FR-003**: Steps MUST be applied to the run-level consensus mask exactly in the order given,
  each to the result of the previous one, before the mask is written to every output level.
- **FR-004**: With no post-processing option, the sequence MUST be `default`. Hole filling MUST NOT
  be applied unless `fill` is in the resolved sequence. Precedence: an explicit `--postprocess`
  (other than `default`) or `--postprocess-file` overrides the steps saved in the prompt file.
- **FR-005**: A radius `R` MUST be either a positive number of run-level voxels (no unit) or a
  positive physical length with a unit among nm, µm (also written um), mm, cm and m.
- **FR-006**: A physical radius MUST be converted to voxels separately along each axis using the
  run level's voxel size and the axes' declared units, so the structuring shape is a sphere of that
  radius in physical space (an ellipsoid in voxels when voxels are not cubic).
- **FR-007**: A voxel radius MUST describe a sphere in voxel space. Morphological steps MUST use
  ball-shaped (or ellipsoidal) structuring shapes, not repeated cross-shaped iterations.
- **FR-008**: Invalid sequences MUST fail before any segmentation, with a message naming the
  offending step: unknown step; missing radius on a step that needs one; radius on `fill`,
  `largest`, `invert` or `none`; non-positive radius; unknown unit; physical radius on a store
  whose axes declare no unit; a physical radius smaller than one voxel along every axis; `default` or `none` combined with other
  steps.
- **FR-009**: The prompt file MAY carry a saved post-processing sequence alongside the prompts, in
  the same step notation. Saved steps are validated like any other source, before segmentation.
- **FR-009a**: The interactive session MUST show the current steps in a post-processing panel,
  pre-filled from `--postprocess`/`--postprocess-file`, or else from the steps saved in a loaded
  prompt file; the user MUST be able to edit them, and previews and exports MUST use the current
  panel values. Invalid edits are refused with the same messages as the command line.
- **FR-009b**: The interactive session MUST be able to load prompts from a prompt file
  (`interactive --prompts FILE`, when FILE exists) and save the current prompts together with the
  current panel steps to that file, so `mask` can reuse both.
- **FR-010**: The old options `--fill-holes`/`--no-fill-holes`, `--dilate`, `--erode` and `--invert`,
  and the corresponding Python API settings, MUST be removed (no backward compatibility).
- **FR-011**: The Python API (prediction and saving) and the interactive session (preview and
  export) MUST accept the same sequence, in the same notation, with identical results to the CLI.
- **FR-012**: The run record and the input log MUST record the applied sequence as an ordered list
  of steps, each with its radius as given and as resolved in voxels per axis, and its source
  (command line, post-processing file, prompt file, or none), sufficient to reproduce the mask.
- **FR-013**: The output mask MUST keep the input's axis units in its metadata, so physical sizes in
  the output mean the same as in the input.
- **FR-014**: The README MUST document the post-processing sequence (steps, units, order, default,
  file form) and that placing prompts on several planes reduces dropouts in multi-axis sweeps.

### Key Entities

- **Post-processing step**: One operation (`fill`, `close`, `open`, `dilate`, `erode`, `largest`,
  `margin`, `invert`) with an optional radius.
- **Radius**: A positive length, either in run-level voxels or in a physical unit; resolved to a
  per-axis voxel radius for a given run level.
- **Post-processing sequence**: The ordered list of steps for a run, given on the command line, in a
  post-processing file or through the API; recorded with the run.
- **Post-processing file**: A small file, separate from the prompt file, holding one sequence.
- **Prompt file** (extended): the prompts and their authoring level, plus an optional saved
  post-processing sequence written by the interactive session.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The clean-up the user needed an external script for (close, fill holes, keep largest
  component, margin) is produced by a single `mask` command, and its output matches the same steps
  applied independently to the raw mask, voxel for voxel, in 100% of test cases.
- **SC-002**: A physical-radius margin applied at two different levels gives margins whose physical
  thickness differs by no more than one run-level voxel along any axis.
- **SC-003**: 100% of invalid sequences in the test set are rejected before segmentation starts,
  with a message naming the offending step.
- **SC-004**: Rerunning with the sequence listed in a run record reproduces the original mask
  exactly in 100% of test cases.
- **SC-005**: The same sequence given through the command line, a post-processing file, a prompt
  file's saved steps, the Python API and the interactive session produces identical masks in 100%
  of test cases.
- **SC-007**: A session's final panel steps, saved with the prompts, are applied by a later `mask`
  run with that prompt file and no post-processing option, giving the same mask as the session's
  export in 100% of test cases.
- **SC-006**: On a run-level mask the size of the user's case (941 × 874 × 874 voxels), the sequence
  `close:3,fill,largest,margin:3` completes in under 5 minutes on a single compute node.

## Assumptions

- Post-processing runs once, on the run-level consensus mask, before the mask is resampled to the
  other output levels (as today); there is no per-level post-processing.
- `largest` counts voxels touching by a face, an edge or a corner as connected, so thin diagonal
  bridges don't split the sample; on a tie, the component found first in scan order is kept.
- `fill` fills holes in 3D (cavities not connected to the volume's border).
- `margin:R` and `dilate:R` add the same voxels (every voxel within distance R); both are kept
  because users think of a safety margin and a dilation differently, and the docs say they are
  equivalent.
- The post-processing file holds the same step notation as `--postprocess`, as an ordered list;
  its exact layout is decided in planning.
- Unit names accepted from axis metadata are the OME-Zarr length units (e.g. "micrometer");
  axes with time or angle units cannot take a physical radius.
- `interactive --prompts FILE` names where prompts are loaded from (if the file exists) and saved
  to; without `--prompts`, saving writes `prompts.json` in the working directory, and `default`
  has nothing to inherit (no steps). Saving is triggered from the napari session (a key and a
  panel button).
- In the Python API there is no prompt file: `default` means no steps unless steps are passed.
- Existing run records written before this feature stay readable as files, but rerunning them
  needs the new notation (no backward compatibility, per the user).
- Bright-region inclusion (adding very bright material that segmentation left out) is out of
  scope, at the user's request.
