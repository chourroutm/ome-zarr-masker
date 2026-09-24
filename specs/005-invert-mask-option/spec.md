# Feature Specification: Invert Mask Output Option

**Feature Branch**: `005-invert-mask-option`

**Created**: 2026-08-26

**Status**: Draft

**Input**: User description: "add an --invert option for the mask"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce a mask-out (background-labeled) output (Priority: P1)

A researcher runs the `mask` command to segment an organ and, for a downstream
tool that expects the organ to be excluded (masked *out*) rather than
highlighted (masked *in*), needs the binary output flipped: background voxels
become `1` and organ voxels become `0`. Today they would have to invert the
mask themselves in a separate post-processing step; this feature lets them
request the inverted result directly from the `mask` command.

**Why this priority**: This is the entire feature — there is no smaller
independently valuable slice.

**Independent Test**: Run `organ-masker mask` twice on the same input, once
without `--invert` and once with it, and confirm the two output masks are
exact voxel-wise complements of each other.

**Acceptance Scenarios**:

1. **Given** a valid input store and prompts, **When** the user runs `mask`
   with `--invert`, **Then** the output mask has `1` at every voxel where the
   non-inverted output would have `0`, and `0` everywhere the non-inverted
   output would have `1`.
2. **Given** the same input, **When** the user runs `mask` without
   `--invert`, **Then** the output is unchanged from current behavior
   (organ voxels `1`, background voxels `0`).
3. **Given** `--invert` combined with `--combine`, `--fill-holes`,
   `--dilate`, and/or `--erode`, **When** the command runs, **Then** those
   post-processing steps are applied to the organ-labeled region first, and
   inversion is applied last, so morphological operations still act on the
   anatomically meaningful region rather than on the inverted background.

---

### Edge Cases

- What happens when no organ is detected (an all-zero mask)? With `--invert`,
  the output MUST become an all-`1` mask covering the entire volume.
- What happens when the entire volume is already labeled as organ (an
  all-one mask, e.g. after aggressive `--dilate`)? With `--invert`, the
  output MUST become an all-`0` mask.
- `--invert` has no interaction with the `interactive` subcommand's
  positive/negative point prompts — those label SAM input clicks, not the
  output mask, and are unaffected by this feature.

## Clarifications

### Session 2026-08-26

- Q: Should the new --invert option also apply to the `interactive` (napari) session's exported mask, or only to the `mask` CLI subcommand's output? → A: `mask` subcommand only — the `interactive` session's export path is unaffected by this feature.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `mask` CLI subcommand MUST accept an `--invert` flag.
- **FR-002**: When `--invert` is not given, output MUST be bit-for-bit
  identical to current behavior (organ voxels `1`, background voxels `0`).
- **FR-003**: When `--invert` is given, the System MUST swap every voxel's
  binary value (`0` becomes `1`, `1` becomes `0`) in the final output mask.
- **FR-004**: Inversion MUST be applied after all other mask shaping for the
  run (multi-prompt `--combine` consensus, `--fill-holes`, `--dilate`,
  `--erode`), so those operations always act on the organ-labeled region.
- **FR-005**: The inverted output MUST use the same `uint8` `{0,1}` encoding
  as the non-inverted output, so downstream readers see no schema or dtype
  difference.
- **FR-006**: `--invert` MUST default to off (current mask-in convention
  unchanged unless explicitly requested).
- **FR-007**: `organ-masker mask --help` MUST describe what `--invert` does
  in terms a user can act on without consulting external docs.
- **FR-008**: The `interactive` subcommand's export path MUST remain
  unaffected by this feature; `--invert` is scoped to the `mask` subcommand
  only.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any given input and prompts, the mask produced with
  `--invert` and the mask produced without it are exact voxel-wise
  complements (an XOR of the two is all `1`s).
- **SC-002**: All existing workflows that do not pass `--invert` produce
  output identical to pre-feature behavior — zero regression.
- **SC-003**: A user reading only `organ-masker mask --help` can correctly
  predict what `--invert` will do to their output.

## Assumptions

- `--invert` is a simple on/off flag (default off), consistent with the
  existing `--overwrite` and `--verbose` flags, rather than a paired
  `--invert`/`--no-invert` toggle — there is no scenario in this codebase
  where the "off" state needs to be forced against an environment default.
- No new provenance metadata (e.g., an "inverted" attribute in output
  OME-Zarr attrs) is written to record that inversion occurred; recording
  that is a possible follow-up but not required for this feature to deliver
  value.
