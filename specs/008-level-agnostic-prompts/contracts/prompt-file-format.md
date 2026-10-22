# Contract: Prompt File Format & Cross-Level Reuse

**Feature**: 008-level-agnostic-prompts | **Date**: 2026-10-09

Extends `specs/001-ome-zarr-sam-masking/contracts/cli.md`'s "Prompt file format" section (the
`--prompts PATH` CLI argument) and the Python API's `add_prompts`/`add_box` methods. Both entry
points are affected; neither's method signatures change.

## Prompt file format (CLI `--prompts`)

```json
{
  "level": 4,
  "objects": [
    {
      "obj_id": 0,
      "points": [{"frame": 120, "xy": [340, 512], "label": 1}],
      "box": {"frame": 120, "xyxy": [300, 480, 380, 560]}
    }
  ]
}
```

- **`level`** (new, **required**, int): the pyramid level `xy`/`xyxy`/`frame` values in this file are
  expressed in -- i.e. whatever level was on screen (or passed as `--level`) when these coordinates
  were read off. Not necessarily the level the `mask` command is run with via its own `--level`.
- A file with no `"level"` key (the pre-feature format) is rejected with a clear error identifying it
  as missing the required field; its coordinates are never guessed at or silently reused as-is.
- Everything else is unchanged from feature 001.

## Python API (`OrganMaskPredictor`)

No method signature changes. `set_volume(store_path, level=...)` already fixes the level for every
subsequent `add_prompts`/`add_box` call until the next `set_volume`; `predict()` now automatically
records that level as the authoring level of the prompt set it builds -- callers do nothing
differently.

## Cross-level reuse behavior

- Running `mask INPUT OUTPUT --prompts PROMPTS --level N` with a `PROMPTS` file whose `"level"`
  differs from `N` converts every coordinate from the file's level to level `N`'s pixel grid before
  anything else happens (before the existing frame/bounds validation, before the sweep).
- Running with `PROMPTS`'s `"level"` equal to `N` (or passing a `PromptSet` built in-process with no
  `level` set) behaves exactly as before this feature -- byte-identical output (FR-006).
- If `PROMPTS`'s `"level"` does not exist in `INPUT`'s pyramid, the command fails with a clear error
  naming the requested and the available levels, the same way an invalid `--level` does today --
  never a silent, best-guess conversion.
- A coordinate that, after conversion, falls outside the run level's bounds is rejected by the
  existing out-of-bounds validation, the same as any other invalid prompt.

## Behavioral contract (testable)

- C-PF-1: A prompt file authored (by coordinate value) against level `A` and run with `--level B`
  (`A != B`, same input) locates the same anatomical feature as the same prompt authored directly
  against level `B` (spec SC-001).
- C-PF-2: A prompt file whose `"level"` equals the run `--level` (or omits `level`/uses the API with
  no explicit level mismatch) produces output identical to the pre-feature behavior (spec SC-002).
- C-PF-3: A prompt file with no `"level"` key is rejected with a clear error; no partial OUTPUT is
  left behind (spec SC-004, mirrors C-CLI-4's existing no-partial-output guarantee).
- C-PF-4: A prompt file whose `"level"` does not exist in `INPUT`'s pyramid is rejected with a clear
  error naming the available levels (spec User Story 3).
- C-PF-5: A point that lands in-bounds at its authoring level but out-of-bounds after conversion to
  the run level (only possible when level metadata maps it there) is still rejected by the existing
  bounds check, never clamped (spec Edge Cases).
- C-PF-6: Conversion maps each axis through that axis's own scale and translation to the nearest
  pixel centre, exact ties to the lower pixel -- correct even when the sweep axis and the in-plane
  axes are downsampled by different factors between the two levels (spec Acceptance Scenario 3).
- C-PF-7: `OrganMaskPredictor.predict()`'s saved run record and a CLI run against an equivalent prompt
  file record the same authoring level (API/CLI parity, mirrors existing C-API-6/C-CLI-6).

## Cross-references requiring alignment (doc-only, no behavior change)

- `specs/001-ome-zarr-sam-masking/contracts/cli.md`'s "Prompt file format" example and
  `specs/001-ome-zarr-sam-masking/data-model.md`'s `Prompt`/`PromptSet` tables predate this feature
  and show the old, level-less format -- update both to the schema above (same pattern feature
  003-bundled-ome-zarr-validation used for its own stale-reference cleanup).
- `README.md`'s prompt-file example and quickstart walkthrough.
