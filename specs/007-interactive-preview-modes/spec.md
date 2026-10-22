# Feature Specification: Tiered Interactive Preview Modes

**Feature Branch**: `007-interactive-preview-modes`

**Created**: 2026-09-24

**Status**: Draft

**Input**: User description: "there is a bug in ome-zarr-masker where the preview does not
display. check how it is made in micro_sam. note that objects are larger (ome-zarr) in real use
cases for ome-zarr-masker. the preview should have 3 modes, 3 shortcuts: single-slice, a few
slices, whole volume (the latter needs to ask for confirmation)". Root-caused: today's single
preview shortcut (`p`) always runs the same full-volume, whole-axis propagation as a final export,
synchronously — fast enough to look fine on small test volumes, but on a real large OME-Zarr
volume it blocks the UI for minutes with no feedback, which reads as "the preview does not
display" rather than "the preview is just very slow."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fast single-slice preview while placing prompts (Priority: P1)

A researcher places or adjusts a point on the slice they're currently viewing and wants
near-instant feedback on just that slice, without waiting for a full-volume computation, so they
can iterate quickly (place, check, adjust, check again) before committing to anything expensive.

**Why this priority**: This directly fixes the reported bug for the single most common interactive
workflow — the existing whole-volume-only preview is what makes iteration on real data feel broken.

**Independent Test**: On a real, large OME-Zarr volume, place a point on the current slice, trigger
single-slice preview, and confirm a result appears within seconds, reflecting only that slice.

**Acceptance Scenarios**:

1. **Given** prompts placed on the currently-viewed slice, **When** the user triggers single-slice
   preview, **Then** a mask is computed using only that slice's prompts and only that slice — no
   propagation to neighboring frames — and the result appears in the existing shared "preview"
   layer.
2. **Given** a real, large volume, **When** single-slice preview is triggered, **Then** it returns
   in a small, bounded time independent of the volume's total depth (SC-001).
3. **Given** the currently-viewed slice has no prompts on it, **When** single-slice preview is
   triggered, **Then** the user gets a clear, actionable message (mirroring the existing "at least
   one positive point or box required" validation) rather than a silent no-op or crash.

---

### User Story 2 - Bounded few-slices preview for local propagation context (Priority: P2)

Once a single-slice result looks right, the researcher wants to check that propagation behaves as
intended in the immediate neighborhood of the current slice, without paying for a full-volume
computation.

**Why this priority**: A useful middle ground between "just this slice" and "the whole (expensive)
volume," directly requested, but not required for User Story 1's fix to already deliver value.

**Independent Test**: Trigger few-slices preview near the middle of a volume and confirm the result
reflects propagation across a bounded window around the current slice, clipped correctly near a
volume boundary.

**Acceptance Scenarios**:

1. **Given** prompts placed within a fixed-size window centered on the current slice, **When** the
   user triggers few-slices preview, **Then** the mask reflects propagation across exactly that
   window (not the whole volume), using only prompts that fall inside it.
2. **Given** the current slice is near the start or end of the volume, **When** few-slices preview
   is triggered, **Then** the window clips to the valid frame range instead of erroring.
3. **Given** a prompt exists on a frame outside the current window, **When** few-slices preview is
   triggered, **Then** that prompt is not included in this mode's result (SC-002).

---

### User Story 3 - Whole-volume preview with a cost confirmation (Priority: P3)

Before exporting, the researcher wants to see the true full-volume result — the same computation
export would produce — but since this is the expensive operation that caused the original bug
report, triggering it must not happen by accident.

**Why this priority**: Preserves today's existing (and still necessary) whole-volume preview
capability, but gated so the original bug — an expensive, blocking operation triggered without the
user realizing its cost — can't recur.

**Independent Test**: Trigger whole-volume preview and confirm a confirmation step is shown before
any computation starts; declining leaves the current preview and session state unchanged.

**Acceptance Scenarios**:

1. **Given** any set of placed prompts, **When** the user triggers whole-volume preview, **Then** a
   confirmation step MUST appear before computation starts, mentioning the cost/time implication.
2. **Given** the confirmation is declined, **When** the user does so, **Then** no computation runs
   and the existing preview (if any) is left exactly as it was.
3. **Given** the confirmation is accepted, **When** computation completes, **Then** the result is
   identical to today's existing `p` behavior — full-axis propagation using every placed prompt —
   shown in the same shared "preview" layer.

---

### Edge Cases

- What happens to prompts outside a mode's scope (few-slices window, or a slice other than the
  current one for single-slice mode)? They're simply excluded from that mode's computation; only
  whole-volume mode is guaranteed to use every prompt the user has placed.
- What happens if the user tries to interact further (place a point, switch slices) while the
  whole-volume confirmation dialog is open? The dialog is modal — it must be answered before any
  other session interaction proceeds.
- What happens on `e` (export)? Export continues to always compute the full whole-volume result
  (matching final output semantics), independent of whichever preview mode was last used — and
  does NOT show the whole-volume-preview confirmation dialog, since export is already a deliberate,
  cost-accepting terminal action, not an easy-to-hit-by-accident key during iteration.
- What happens if the user triggers a preview mode while a single-slice or few-slices computation
  is already running in the background? The new trigger is a no-op while the busy indicator is
  showing — nothing is cancelled or queued (FR-011).

## Clarifications

### Session 2026-09-24

- Q: Should preview computation (any of the 3 modes) block the napari GUI while it runs, or run in
  the background so the UI stays responsive with a progress indicator? → A: Async for single-slice
  and few-slices modes (background thread + a lightweight busy indicator, since their whole point
  is responsiveness — even a brief freeze would echo the original bug); synchronous/blocking for
  whole-volume mode, since it's already gated by a confirmation the user just deliberately answered.
- Q: If the user triggers another preview while an async single-slice or few-slices computation is
  still running, what should happen? → A: Ignore the new trigger while busy — the busy indicator is
  visible, and the keypress is a no-op until the in-flight computation finishes. No cancellation or
  queueing logic.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The interactive session MUST offer three distinct preview modes: single-slice,
  few-slices, and whole-volume.
- **FR-002**: Each mode MUST have its own dedicated keyboard shortcut, distinct from each other and
  from the existing `n`/`y`/`e` bindings.
- **FR-003**: Single-slice mode MUST compute using only the currently-viewed frame and only the
  prompts placed on it — no propagation to any other frame.
- **FR-004**: Few-slices mode MUST compute using a fixed-size window of frames centered on the
  currently-viewed frame, clipped to the volume's valid frame range near a boundary, using only
  prompts that fall within that window.
- **FR-005**: Whole-volume mode MUST reproduce today's existing `p` behavior exactly: full-axis
  propagation using every placed prompt.
- **FR-006**: Triggering whole-volume mode MUST show a confirmation step before any computation
  starts; declining MUST leave the current preview and session state unchanged.
- **FR-007**: All three modes MUST write their result to the same single shared "preview" labels
  layer that exists today, rather than creating separate layers per mode.
- **FR-008**: `e` (export) MUST continue to always perform the full whole-volume computation
  regardless of the last-used preview mode, and MUST NOT show the whole-volume-preview confirmation
  step.
- **FR-009**: Single-slice and few-slices mode cost MUST scale with the number of frames they
  actually process (1, or the fixed window size) — not with the volume's total depth.
- **FR-010**: Single-slice and few-slices mode computation MUST run without blocking the session's
  UI (e.g., on a background thread), showing a visible busy/in-progress indicator for its duration;
  whole-volume mode MAY run synchronously/blocking, since it is already gated behind an explicit,
  just-answered confirmation step.
- **FR-011**: While a single-slice or few-slices computation is in flight, triggering any preview
  mode (including the same one again) MUST be a no-op — no new computation starts, nothing is
  cancelled or queued — until the in-flight one finishes.

## Key Entities

- **Preview mode**: one of `single-slice`, `few-slices`, `whole-volume`; determines which frames
  and which of the placed prompts are used for a given preview computation.
- **Few-slices window**: a fixed-size, current-slice-centered, boundary-clipped range of frame
  indices used by few-slices mode.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a real, large volume, single-slice preview returns within a few seconds —
  order-of-magnitude faster than the existing whole-volume-only behavior, and independent of the
  volume's total depth.
- **SC-002**: Few-slices preview's cost and included prompts scale with the fixed window size, not
  overall volume depth — verified by comparable timing across volumes of very different total
  depth, and by confirming out-of-window prompts are excluded from the result.
- **SC-003**: Whole-volume computation never runs without an explicit, answered confirmation step
  immediately preceding it.
- **SC-004**: A user unfamiliar with this feature can trigger the fast single-slice mode and get a
  usable result on a real volume without first reading documentation, simply by trying the most
  "default-feeling" of the three shortcuts.
- **SC-005**: The session's UI (point/box placement, slice navigation) remains responsive — never
  frozen — for the entire duration of a single-slice or few-slices computation; a visible busy
  indicator is present the whole time, and repeated triggering during that window produces no
  duplicate or queued computations.

## Assumptions

- The few-slices window size is a fixed default of ±5 frames around the current slice (11 frames
  total, clipped near a volume boundary), not user-configurable in this feature's first version;
  making it configurable is a possible follow-up, not required here.
- Whole-volume preview and export perform the identical underlying full-volume computation; only
  the explicit whole-volume *preview* shortcut is gated by a confirmation step, since it's the one
  an iterating user could trigger unintentionally — export is already a deliberate final action.
- Delivering single-slice and few-slices modes requires the shared masking engine
  (`compute_mask`) to support processing a bounded frame range instead of always the full swept
  axis; this is a shared-engine change, not one confined to the interactive session's own code. The
  CLI `mask` command's behavior (always whole-volume) is unaffected and stays out of scope for this
  feature.
- The existing single "preview" labels layer is reused for all three modes' output rather than
  adding per-mode layers, keeping "what am I looking at" unambiguous (FR-007).
- Single-slice and few-slices modes require a background-thread execution mechanism in
  `interactive.py`'s `launch()` (e.g. a Qt/napari worker) plus a simple busy-state flag guarding
  FR-011's ignore-while-busy rule; whole-volume mode does not need this, since it stays
  synchronous behind its confirmation step (FR-010).
