# Feature Specification: Level-Agnostic Prompt Coordinates

**Feature Branch**: `008-level-agnostic-prompts`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "save the prompts in level-agnostic coordinates, but keep a trace at which level they were given"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Rerun masking at a different level without re-authoring prompts (Priority: P1)

A researcher previews a large volume at a coarse (fast-to-load) pyramid level, places landmark
prompts on the structure of interest, and runs the masking pipeline. Later, wanting a higher-fidelity
mask, they rerun the same prompt file against a finer pyramid level of the same input, without
re-clicking any points.

**Why this priority**: This is the core problem motivating the feature. Today, prompts are recorded
as raw pixel coordinates tied to whichever level was on screen when they were authored; reusing that
same file at a different level silently shifts every point to the wrong physical location and produces
a wrong mask with no error. Fixing this is the entire value of the feature.

**Independent Test**: Author a prompt set against a coarse level, save it, rerun the masking pipeline
pointing at a finer level of the same input, and confirm the resulting mask targets the same anatomical
location as the coarse-level run (not a scaled-off location).

**Acceptance Scenarios**:

1. **Given** a saved prompt set authored while viewing level 4, **When** the masking pipeline is run
   against level 2 of the same input, **Then** each point and box resolves to the pixel location in
   level 2 that corresponds to the same physical location it marked at level 4.
2. **Given** a saved prompt set authored while viewing level 4, **When** the masking pipeline is run
   again against level 4, **Then** the resulting mask is identical to a run made before this feature
   existed (no regression for the same-level case).
3. **Given** a prompt set with a frame index on the sweep axis, **When** the pipeline is run at a level
   where that axis is downsampled by a different factor than the in-plane axes, **Then** the frame index
   resolves to the slice corresponding to the same physical position along that axis.

---

### User Story 2 - See which level a prompt was originally authored at (Priority: P2)

A researcher reviewing a saved prompt file, or debugging an unexpected mask, wants to know at what
resolution each prompt was originally placed, since a point clicked on a very coarse level carries more
positional uncertainty than one placed on a fine level.

**Why this priority**: Important for trust and debugging, but the pipeline must already behave
correctly (User Story 1) before this traceability information is useful.

**Independent Test**: Author a prompt set at a known level, save it, open the saved file, and confirm
the originating level is recorded per prompt (or per prompt set) in a human-readable way, without
needing to reverse-engineer it from pixel values.

**Acceptance Scenarios**:

1. **Given** a prompt authored while viewing level 3, **When** the prompt set is saved, **Then** the
   saved record includes the level it was authored at.
2. **Given** a saved prompt file, **When** it is inspected, **Then** the recorded authoring level is
   purely informational and does not change which level the pipeline will run at (the run level is
   still chosen independently, e.g. via CLI/config).

---

### User Story 3 - Clear error instead of silent misplacement when conversion isn't possible (Priority: P3)

A researcher runs a saved prompt set against an input whose pyramid no longer has enough levels to
match the one the prompt set was authored against (e.g. a reprocessed or different-resolution input).

**Why this priority**: A safety net for a less common but plausible situation; the primary paths
(Stories 1-2) deliver the main value on their own.

**Independent Test**: Load a prompt set whose recorded authoring level does not exist in the current
input's pyramid, run the pipeline, and confirm a clear, actionable error is raised rather than a
coordinate being silently misapplied.

**Acceptance Scenarios**:

1. **Given** a prompt set authored at level 5, **When** the current input only has levels 0-3,
   **Then** the system raises a clear error identifying the mismatch rather than guessing a scale.

### Edge Cases

- A point placed very close to the edge of the frame at a coarse level may, after conversion, round to
  a pixel just outside the bounds of a much finer level; the system must still raise the existing
  out-of-bounds validation error rather than clamping silently.
- The sweep axis may be downsampled by a different factor than the in-plane axes (anisotropic
  pyramids); frame-index conversion must use that axis's own factor, not the in-plane factor.
- A prompt file created before this feature exists in the old, purely pixel-based format; loading it
  must fail with a clear message rather than being silently misinterpreted as the new format (see
  Assumptions).
- Converting a coordinate from a coarse level to a finer level and back to the original coarse level
  must reproduce the original pixel location (round-trip stability), modulo the unavoidable rounding
  of going through an intermediate finer grid.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST store prompt point and box coordinates in a form that is independent of the
  pyramid level that was active when the prompt was authored.
- **FR-002**: System MUST record, alongside each saved prompt (or prompt set), which pyramid level was
  active when it was authored, as traceability metadata.
- **FR-003**: The recorded authoring level (FR-002) MUST be informational only: it MUST NOT be required
  in order to use the prompt, and MUST NOT by itself restrict or determine which level a later run uses.
- **FR-004**: When the masking pipeline runs at a given level, System MUST resolve every stored prompt
  coordinate (points, box corners, and sweep-axis frame index) to that level's pixel grid before use,
  correctly accounting for cases where axes are downsampled by different factors across levels.
- **FR-005**: System MUST validate the resolved, level-specific coordinates against the selected run
  level's bounds and raise the existing actionable out-of-bounds error when they fall outside it, even
  when the original authored coordinate was in-bounds at its own level.
- **FR-006**: System MUST produce a mask for a same-level rerun (authoring level == run level) that is
  unchanged from the current (pre-feature) pixel-coordinate behavior, so existing single-level workflows
  do not regress.
- **FR-007**: System MUST reject prompt files written in the prior, purely pixel-based format with a
  clear, actionable error rather than silently reinterpreting their raw pixel values as level-agnostic
  coordinates.
- **FR-008**: System MUST raise a clear, actionable error when a loaded prompt's recorded authoring
  level does not correspond to any level available in the current input, instead of attempting a
  best-guess conversion.

### Key Entities

- **Prompt**: A landmark (points and/or box) placed on one frame for one target object. Gains a
  level-agnostic coordinate representation (replacing today's raw, level-tied pixel coordinates) plus
  a recorded authoring level for traceability.
- **Prompt Set**: The collection of prompts for one run. Its on-disk format gains the per-prompt
  authoring-level trace; existing bare pixel-coordinate files are no longer accepted as-is.
- **Pyramid Level**: An existing concept (an OME-Zarr multiscale resolution) that a prompt now
  references by traceability only, decoupled from which level a prompt is usable at.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A prompt set authored at one level and reused unmodified at any other level of the same
  input produces a mask targeting the same anatomical location as a mask produced from a prompt set
  authored directly at that second level, for every available level pair in a multiscale input.
- **SC-002**: Rerunning an existing prompt set at its original authoring level produces a byte-identical
  mask to the pre-feature behavior, with zero regressions across the existing test suite.
- **SC-003**: Opening any saved prompt file lets a researcher determine the authoring level of every
  prompt without consulting any other file or computing anything from pixel values.
- **SC-004**: Attempting to run a stale (prior-format or level-mismatched) prompt file yields an
  actionable error message in 100% of cases, with zero instances of silent misplacement.

## Assumptions

- The level-agnostic coordinate representation relies on the same nested-grid relationship between
  pyramid levels that the mask writer already uses to resample its output across levels (per feature
  001-ome-zarr-sam-masking): a level's shape tells you exactly how many of its pixels correspond to one
  pixel of any other level. No new, separately-tracked physical unit system is introduced.
- This is a breaking change to the prompt file's on-disk schema (FR-007): no automatic migration path
  for prompt files saved before this feature is in scope. Existing saved prompt files must be
  re-authored (via the interactive tool) after upgrading.
- Coordinate conversion between levels resolves to the nearest pixel on the target level's grid,
  consistent with the nearest-neighbor convention already used when resampling masks across levels.
- A prompt set is always reused against the same input volume (the same OME-Zarr store) it was
  originally authored against, only potentially at a different level of that same store's pyramid;
  reuse across genuinely different input volumes is out of scope.
- Remote (non-local-filesystem) input sources remain out of scope, consistent with prior project
  direction; this feature only concerns how prompt coordinates relate across levels of one local input.
