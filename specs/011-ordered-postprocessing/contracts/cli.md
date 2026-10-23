# Contract: CLI changes

**Feature**: 011-ordered-postprocessing | **Date**: 2026-10-23

Extends the `mask` and `interactive` contracts of features 001, 007, 009 and 010.

## Removed options (no backward compatibility, FR-010)

`--fill-holes`, `--no-fill-holes`, `--dilate`, `--erode`, `--invert` (on `mask`). Using one is an
argparse usage error (exit 2) whose message names `--postprocess`.

## `ome-zarr-masker mask INPUT OUTPUT --prompts FILE ...`

- `--postprocess STEPS` (default: `default`) or `--postprocess-file FILE` (mutually exclusive;
  both given → usage error, exit 2). Notation: `contracts/postprocess-notation.md`.
- C-CLI-PP-1: Resolution and precedence as in research R5; `default` uses the prompt file's saved
  steps, else none.
- C-CLI-PP-2: Every notation, unit, file or saved-steps error exits 1 before segmentation, with one
  line on stderr naming the step and its source (`--postprocess`, the file path, or the prompt
  file path), and no output.
- C-CLI-PP-3: The run record and input log list the resolved steps and their source (FR-012).

## `ome-zarr-masker interactive INPUT ...`

- New: `--prompts FILE` (default `prompts.json`): loaded at start if it exists (prompts converted to
  the session level; saved steps become the panel's value unless `--postprocess`/`--postprocess-file`
  is given), and written when the user saves.
- New: `--postprocess STEPS` (default `default`) / `--postprocess-file FILE`, mutually exclusive,
  validated like `mask` before the viewer opens (exit 1 on error).
- C-CLI-PP-4: The napari window has a post-processing panel (text field pre-filled with the
  resolved steps, Apply, Save prompts) and a `w` key that saves; previews (`s`, `f`, `p`) and
  export (`e`) use the panel's current steps; an invalid edit shows the CLI's message and keeps the
  previous steps.
- C-CLI-PP-5: Saving writes the prompts and the panel's current steps to `--prompts FILE`
  (feature 008 format + `"postprocess"`), so `mask ... --prompts FILE` with no `--postprocess`
  applies the same steps (SC-007).
