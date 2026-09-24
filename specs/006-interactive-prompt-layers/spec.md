# Feature Specification: Interactive Prompt Layers (Points + Box)

**Feature Branch**: `006-interactive-prompt-layers`

**Created**: 2026-09-24

**Status**: Draft

**Input**: User description: "spec out the prompt features: start with 3 layers for positive
point, negative point and positive box. the buttons n/y still flip between positive and negative
by moving the point to the corresponding layer. change appearance of box to translucent no depth,
opacity 100%, edge 1 color lime, fill color #00000000 (transparent). change appearance of positive
point to cross size 7 lime no edge. change appearance of negative point to disc size 6 red no
edge."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Place and flip point prompts across dedicated layers (Priority: P1)

A researcher opens the interactive session and clicks to place landmark points. Each point is
immediately visible as either a positive marker or a negative marker, living in its own layer
rather than being a single mixed layer recolored per point. Selecting one or more positive points
and pressing `n` moves them out of the positive layer and into the negative layer; selecting
negative points and pressing `y` moves them back.

**Why this priority**: This is the direct replacement for the existing single-layer,
recolor-in-place point workflow, and is required before box prompts are usable at all (the box
layer's appearance rules don't depend on this, but the "three layers" structure is the foundation
the rest of the feature builds on).

**Independent Test**: Open the interactive session, place a point (appears in the positive-points
layer as a lime cross), select it and press `n` (it disappears from the positive layer and
reappears in the negative-points layer as a red disc), select it there and press `y` (it moves
back).

**Acceptance Scenarios**:

1. **Given** an empty session, **When** the user clicks to place a new point, **Then** it appears
   in the positive-points layer, rendered as a lime cross-shaped marker with no border.
2. **Given** one or more points selected in the positive-points layer, **When** the user presses
   `n`, **Then** those points are removed from the positive-points layer and added to the
   negative-points layer at the same frame/coordinates, rendered as red disc markers with no
   border.
3. **Given** one or more points selected in the negative-points layer, **When** the user presses
   `y`, **Then** those points move back to the positive-points layer, rendered as lime crosses.
4. **Given** a point already in the positive-points layer, **When** the user selects it and
   presses `y` (already positive), **Then** nothing changes (no-op, not an error).
5. **Given** a point already in the negative-points layer, **When** the user selects it and
   presses `n` (already negative), **Then** nothing changes (no-op, not an error).
6. **Given** a point just flipped by `n` (now in the negative-points layer), **When** the user
   immediately presses `y` without reselecting anything, **Then** the point flips straight back to
   the positive-points layer, because the flip left it selected in its new layer.
7. **Given** a point selected in the positive-points layer, **When** the user switches to interact
   with the negative-points layer (without pressing `n`/`y` first) and places a new point there,
   **Then** the original point's selection in the positive-points layer has been cleared, so a
   subsequent `n`/`y` keypress affects only the newly placed point, not the forgotten one.

---

### User Story 2 - Draw a positive box prompt (Priority: P2)

The same researcher, instead of (or in addition to) points, draws a rectangle around the region of
interest on a slice. The rectangle renders as a translucent lime-outlined, fully transparent-filled
box with no depth shading, distinct from the point layers, and is used as a positive box prompt
for masking (the box-prompt engine path already exists; only points currently reach it from the
interactive session).

**Why this priority**: Builds on User Story 1's three-layer foundation but is independently usable
— a user can rely on box-only prompting without ever using points, and vice versa.

**Independent Test**: Open the interactive session, draw a rectangle in the positive-box layer
(renders as a lime-outlined, transparent-filled box), press `p` to preview; the resulting mask
reflects the box region the same way it would from an equivalent CLI prompt file with a `box`
entry.

**Acceptance Scenarios**:

1. **Given** an empty session, **When** the user draws a rectangle in the positive-box layer,
   **Then** it renders with a 1px lime edge, fully transparent fill (`#00000000`), 100% opacity,
   and no depth shading relative to other layers (`translucent, no depth` blending).
2. **Given** a rectangle drawn in the positive-box layer, **When** the user presses `p` (preview)
   or `e` (export), **Then** the box is sent to the masking engine as a positive box prompt on its
   frame, alongside any point prompts from the positive/negative point layers.
3. **Given** the positive-box layer's drawing tools, **When** the user attempts to draw a
   non-rectangle shape (ellipse, line, polygon, path), **Then** the shape is not persisted in the
   layer — only rectangles remain.

---

### Edge Cases

- What happens when a selection spans both the positive- and negative-points layers at once and
  the user presses `n` or `y`? napari auto-selects a point the instant it's placed (its own
  `selected_data` is set to the new point), and normally that selection lingers even after the
  user switches to a different layer — so without a mitigation, placing a point in positive, then
  switching to negative and placing a second point, would leave *both* points selected, and
  flipping the second would silently also flip the first, forgotten one. To prevent that: switching
  which layer is active MUST clear the selection of the layer that just lost active status, so a
  leftover selection from an earlier action can never bleed into a later keypress. `n`/`y` remain
  bound at the viewer level (not per-layer) and act on whichever layer(s) currently hold a
  selection; in practice, after the auto-clear rule, that's normally just the layer the user is
  actively working in — except immediately after a flip (see below), which is a deliberate,
  same-instant continuation, not a stale leftover.
- What happens to a point's selection immediately after it's flipped by `n`/`y`? It MUST remain
  selected, now in its destination layer, so pressing the opposite key again right away flips it
  straight back without having to reselect it. This does not trigger the auto-clear-on-switch rule
  above, because a flip doesn't change which layer is "active" — only explicit layer switching
  does.
- What happens when a second rectangle is drawn in the positive-box layer on a frame that already
  has one? The new rectangle replaces the existing one for that frame (a frame carries at most one
  box prompt, matching the underlying `Prompt.box` field, which is singular, not a list).
- What happens with a degenerate (zero-area / click-without-drag) rectangle? It is rejected the
  same way a malformed box is already rejected by prompt validation (`x0 < x1` and `y0 < y1`
  required).
- What happens to points/boxes on preview/export if the positive-box layer is empty? Masking
  proceeds with point prompts alone, exactly as it does today (a box is optional, matching the
  existing CLI prompt-file contract).

## Clarifications

### Session 2026-09-24

- Q: When a second rectangle is drawn in the positive-box layer on a frame that already has one,
  what should happen? → A: Replace — the newest box wins for that frame, matching `Prompt.box`
  being a single optional field rather than a list.
- Q: When a selection spans both the positive- and negative-points layers at once, how should
  `n`/`y` behave? → A: Global keys, filter per layer, refined after confirming (via napari's
  `Points.add` source) that a newly placed point is always auto-selected and that selection
  lingers across an active-layer switch: switching the active layer MUST clear the selection of
  the layer losing focus, so a forgotten selection can't bleed into a later keypress on a different
  layer.
- Q: Should a point stay selected immediately after `n`/`y` flips it, so pressing the opposite key
  right away flips it back? → A: Yes — the flip MUST leave the point selected in its destination
  layer. This is unaffected by the auto-clear-on-switch rule above, since a flip doesn't change
  which layer is active.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The interactive session MUST present three independently visible layers: a
  positive-points layer, a negative-points layer, and a positive-box layer, replacing the current
  single "prompts" points layer that recolors points in place.
- **FR-002**: A newly placed point MUST be added to the positive-points layer by default.
- **FR-003**: `n`/`y` MUST be bound at the viewer level, not per-layer, so they act on whichever
  layer(s) currently hold a selection regardless of which layer is active. Selecting one or more
  points in the positive-points layer and pressing `n` MUST move them into the negative-points
  layer (removed from one, added to the other at the same frame/coordinates); pressing `n` again on
  already-negative points MUST be a no-op.
- **FR-004**: Selecting one or more points in the negative-points layer and pressing `y` MUST move
  them into the positive-points layer; pressing `y` again on already-positive points MUST be a
  no-op. If a selection exists in both point layers at once, a single `n` or `y` keypress MUST
  apply both layers' corresponding effects (FR-003/FR-004 both fire), not just the active layer's.
- **FR-004a**: Whenever the active layer changes (the user switches which layer they're
  interacting with), the layer that just lost active status MUST have its selection cleared. This
  prevents a point auto-selected by a prior placement (napari selects every newly added point) from
  silently lingering into a later, unrelated `n`/`y` keypress on a different layer.
- **FR-004b**: When `n`/`y` moves a point to its destination layer, that point MUST remain selected
  in the destination layer immediately afterward, so pressing the opposite key again right away
  flips it back without reselecting. This is a same-instant continuation of the user's action, not
  subject to the FR-004a auto-clear rule (a flip does not change which layer is active).
- **FR-005**: The positive-points layer MUST render markers as a lime cross (`+`) symbol, size 7,
  with no visible edge/border.
- **FR-006**: The negative-points layer MUST render markers as a red disc symbol, size 6, with no
  visible edge/border.
- **FR-007**: The positive-box layer MUST only ever contain rectangle shapes; a non-rectangle shape
  (ellipse, line, polygon, path) drawn in it MUST NOT be persisted as a prompt.
- **FR-008**: The positive-box layer MUST render shapes with: `translucent, no depth` blending,
  100% opacity, a 1px lime edge, and a fully transparent fill (`#00000000`).
- **FR-009**: Preview (`p`) and export (`e`) MUST read prompts from all three layers: positive and
  negative points as labeled point prompts, and the positive-box layer's rectangle(s) as box
  prompts — feeding the same underlying prompt model (`Prompt.point_coords`/`point_labels`/`box`)
  the CLI's prompt-file path already produces, so interactive and CLI prompting stay equivalent.
- **FR-010**: At most one box prompt MUST exist per frame; drawing a second rectangle on an
  already-boxed frame MUST replace the earlier one for that frame.

### Key Entities

- **Positive-points layer**: napari points layer holding include/positive landmark prompts only.
- **Negative-points layer**: napari points layer holding exclude/negative landmark prompts only.
- **Positive-box layer**: napari shapes layer, rectangle-only, holding at most one box prompt per
  frame.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can tell a point's polarity and any box prompt apart at a glance, purely from
  marker shape/color and box styling, without consulting a legend or documentation.
- **SC-002**: Flipping a point's polarity is a single keypress (`n` or `y`) with the point visibly
  relocated to the other layer's styling immediately after the keypress, and remains selected there
  so an immediate repeat keypress flips it straight back with no reselection step.
- **SC-003**: No non-rectangle shape ever persists in the positive-box layer, verified by drawing
  each of napari's other shape tools and confirming none survive in that layer's data.
- **SC-004**: A mask produced from this interactive UI (points + box) is identical to a mask
  produced from an equivalent CLI prompt-file with the same coordinates, labels, and box, for the
  same input volume and settings.

## Assumptions

- This feature only restructures how prompts are *placed and displayed* in the interactive
  session; it does not add multi-object (`obj_id`) UI — all points and the box continue to apply
  to the single implicit object, matching current interactive-session scope.
- "No depth" in the box layer's appearance refers to the layer not participating in 3D
  depth-based occlusion/shading relative to other layers (i.e. `translucent_no_depth`-style
  blending), not to the box prompt itself carrying a z-extent — boxes remain 2D, per-frame regions
  exactly as `Prompt.box` already models them.
- The existing single mixed "prompts" points layer and its `positive` feature-based recoloring are
  fully replaced by the two new point layers; no feature flag or fallback to the old single-layer
  behavior is provided.
- `OrganMaskPredictor.add_box` (already implemented, currently unused by the interactive session)
  is the mechanism the box layer's prompts are expected to reach the masking engine through; this
  feature does not change that method's contract.
