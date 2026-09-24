# Implementation Plan: Interactive Prompt Layers (Points + Box)

**Branch**: `006-interactive-prompt-layers` | **Date**: 2026-09-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-interactive-prompt-layers/spec.md`

**Architecture note**: The user asked to weigh a custom napari "prompt" layer type (a new plugin
dependency unifying point add/select/delete, box add/select/resize/delete, and a swap action) as
an alternative to the spec's three-built-in-layers design. Researched and rejected — see
research.md R1. Summary: napari's plugin system has no extension point for registering a new layer
*type* (only readers/writers/widgets/commands/etc. for the existing 7 built-in types), so this
would require reaching into undocumented internals; no real-world napari+SAM plugin does this
either (they all compose built-in Points/Shapes layers, same as this plan); and nothing in the
user's ask is actually missing from the built-in composition (Shapes already gives resize/select/
delete for free). The three-layer design from spec.md stands.

## Summary

Replace the interactive session's single "prompts" points layer (which recolors points in place)
with three napari layers — positive-points, negative-points, positive-box — each with fixed
appearance styling, plus viewer-level `n`/`y` keybindings that move points between the two point
layers with auto-clear-on-layer-switch and post-flip selection continuity (spec.md FR-003/004/
004a/004b). The box layer feeds the already-implemented but currently-unused
`OrganMaskPredictor.add_box`. Entirely contained in `interactive.py`; no new dependency.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged)

**Primary Dependencies**: `napari` (existing `[interactive]` extra, version floor unchanged) — no
new dependency. A custom-layer-type napari plugin was considered and rejected (research R1); this
feature composes napari's built-in `Points` (×2) and `Shapes` (×1) layers entirely through public,
documented `napari.Viewer`/`Layer` API (`add_points`, `add_shapes`, `layer.events`, `bind_key`).

**Storage**: Unchanged — OME-Zarr v0.5. This feature changes prompt *placement UI* only; the
written mask format is untouched.

**Testing**: `pytest`. `InteractiveSession`'s headless core (prompt bookkeeping, `preview`,
`export`) is fully testable without napari/Qt/a display, per the existing pattern in
`tests/integration/test_us6_interactive.py`; `launch()` itself (the actual napari GUI wiring —
layers, keybindings, colors, auto-clear-on-switch) already carries `# pragma: no cover - requires
napari + a display` and has zero automated coverage today. This feature's testable surface is the
headless core (frame/point/box bookkeeping, merged per-frame prompt construction, SC-004 parity
with the CLI path) plus a manual `quickstart.md` walkthrough for the GUI-only parts (layer
appearance, keybinding feel) — this mirrors, not widens, the project's existing testing boundary
for `InteractiveSession`.

**Target Platform**: Unchanged — Linux/macOS workstation; the interactive session additionally
requires a display, already true today.

**Project Type**: Single Python package; the napari view remains a thin, already-isolated layer
over the headless core (`interactive.py`'s own module docstring already states this design intent).

**Performance Goals** (Principle IV): No new performance target. This is a prompt-placement UI
change over the same masking engine; the masking cost budget (spec 001: 512³ volume masked in <5
minutes on GPU) is untouched. Layer/event bookkeeping (moving points between layers, merging a
frame's points+box into one prompt) is O(number of placed prompts), negligible next to inference
cost.

**Constraints**: No new runtime dependency (research R1 rules out a custom-layer-type plugin).
Point add/select/delete and box add/select/resize/delete MUST come from napari's built-in
`Points`/`Shapes` layer interactions — already free, no code needed beyond adding the layers and
the appearance/rectangle-only constraints from spec.md FR-005/006/007/008.

**Scale/Scope**: Same single-user, single-session scope as the existing interactive session.
Primarily one file, `src/organ_masker_lite/interactive.py`: the headless core gains box
bookkeeping and merges each frame's points+box into a single `Prompt` before reaching the
predictor; `launch()` grows from one points layer to three layers plus the new keybinding/event
logic. Plus one small, backward-compatible addition to `api.py`: `OrganMaskPredictor.add_points`
gains an optional `box` parameter (research R2 — confirmed via the installed SAM2 source that two
separate `add_points`/`add_box` calls for the same frame silently drop one or the other, since
SAM2's `clear_old_points=True` default replaces rather than accumulates per-frame prompts). No
changes to `sam2.py`, `prompts/model.py`, or `cli.py`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.0 (four core principles):

- **I. Code Quality Standards** — PASS. The custom-layer-type/new-plugin alternative was
  researched and explicitly rejected as unjustified complexity (research R1) — "prefer the
  simplest solution that satisfies the requirement" is exactly why the built-in-layer composition
  stands. No Complexity Tracking entry is needed because the more complex path was *not* taken.
- **II. Test Discipline (NON-NEGOTIABLE)** — PASS, with a disclosed, pre-existing limitation
  carried forward unchanged: `launch()`'s napari-GUI wiring has no automated coverage today (no
  display in this environment's test runs), and this feature doesn't change that boundary — it
  adds behavioral tests for everything on the headless-core side of that boundary (box bookkeeping,
  merged prompt construction, SC-004 parity) and relies on `quickstart.md`'s manual walkthrough for
  the GUI-only appearance/keybinding behavior, exactly matching how the existing points-layer UI is
  (not) tested today.
- **III. Disciplined Version Control** — PASS (planned). Decomposed into atomic commits: (1) box
  bookkeeping + merged-prompt construction in the headless core, (2) the three-layer `launch()`
  rewrite (layers + appearance), (3) `n`/`y` keybinding + auto-clear/continuity event wiring, (4)
  rectangle-only enforcement on the box layer, (5) tests — each leaving the suite green.
- **IV. Performance Requirements** — PASS. No new target; justified above under Performance Goals.

No unjustified violations. No Complexity Tracking entries needed.

**Post-Phase-1 re-check**: Phase 1 design (research R2) revealed that `api.py` needs one small,
backward-compatible change (an optional `box` parameter on `add_points`) beyond the
`interactive.py`-only scope assumed going into Phase 0. This does not change the Constitution Check
outcome on any principle — it's strictly smaller than a new method, has no new callers to migrate,
and was discovered specifically *by* the Principle-I-driven research (verifying against the actual
SAM2 source rather than assuming), which is the process working as intended, not a gap in it.

## Project Structure

### Documentation (this feature)

```text
specs/006-interactive-prompt-layers/
├── plan.md              # This file
├── research.md          # Phase 0 output (custom-layer-type decision, prompt-merge decision)
├── data-model.md         # Phase 1 output (three-layer model, merged per-frame Prompt)
├── quickstart.md        # Phase 1 output
├── contracts/            # Phase 1 output (interactive-session UI contract)
│   └── interactive-ui.md
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
src/organ_masker_lite/
├── api.py                     # changed: OrganMaskPredictor.add_points gains an optional `box`
│                               #          parameter (research R2) so a frame's points+box reach
│                               #          SAM2 in one call; add_box unchanged, still works alone
└── interactive.py             # changed (the feature's primary file):
                                #   - headless core: _boxes bookkeeping, add_box/clear_points
                                #     updates, preview() merges points+box per frame into one
                                #     add_points(..., box=...) call (research R2)
                                #   - launch(): positive/negative Points layers + positive-box
                                #     Shapes layer, appearance styling (FR-005/006/008),
                                #     rectangle-only enforcement (FR-007), viewer-level n/y
                                #     keybindings with auto-clear-on-switch (FR-004a) and
                                #     post-flip selection continuity (FR-004b)

tests/
└── integration/
    └── test_us6_interactive.py  # changed: extend the headless-core tests for box bookkeeping,
                                  #          merged points+box prompts, and CLI-parity (SC-004);
                                  #          real_backend-gated, matching the file's existing tests
```

**Structure Decision**: Everything lives in the existing `interactive.py`, matching its own stated
design (headless core + thin napari view, single file). No new module, no new package, no new
dependency — the three-layer UI and the box-bookkeeping/merge logic are both additions to the one
file that already owns "interactive session" responsibility end to end.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

No constitution violations; no entries required. (The one complexity-increasing alternative
considered — a custom napari layer type / new plugin dependency — was rejected rather than taken;
see research.md R1 for the full analysis.)
