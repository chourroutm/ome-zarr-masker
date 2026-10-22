# Phase 0 Research: Level-Agnostic Prompt Coordinates

**Feature**: 008-level-agnostic-prompts | **Date**: 2026-10-09

No `[NEEDS CLARIFICATION]` markers remained in the spec, so this phase resolves implementation-level
design questions against the existing codebase rather than open unknowns.

## R1: What "level-agnostic" actually resolves to (conversion part superseded by R8)

**Decision**: A prompt's coordinates stay exactly what they are today -- pixels in the authoring
level's own grid -- plus one new integer, the authoring level index, on the `PromptSet`. "Level
agnostic" is achieved not by inventing a new coordinate system, but by making the *pipeline*
responsible for converting those pixels to whichever level it actually runs at, using the per-axis
ratio between the two levels' shapes.

**Rationale**: `io/writer.py::_nn_resize` already resamples the computed mask across every output
level using exactly this mechanism -- `np.arange(t) * s // t` per axis, driven purely by `mask.shape`
vs. `target_shape` -- and deliberately ignores the `coordinateTransformations` scale/translation
metadata for the resize math itself (that metadata is only copied into the *output*'s metadata, not
consulted to compute the resample). Reusing the same shape-ratio idea for prompt coordinates means:
no dependency on `coordinateTransformations` being present or internally consistent, no new unit
system to document or get wrong, and a design that mirrors an already-reviewed, already-tested
pattern in this codebase.

**Alternatives considered**:
- *Physical/world coordinates via `coordinateTransformations`*: the spec's first-drafted Assumption
  (see spec.md history) before this research. Rejected after reading `_nn_resize`: it would be a
  second, parallel mechanism for level-to-level mapping that disagrees in principle (if a store's
  `coordinateTransformations` scale ever didn't exactly match its datasets' shape ratios) with the one
  the writer already uses, for no added correctness in a tool whose own output resampling doesn't
  rely on it either.
- *Normalized `[0, 1)` fractional coordinates*: equivalent in power to the shape-ratio approach but
  adds a conversion step (and rounding behavior) even for the common same-level case; rejected in
  favor of keeping same-level storage pixel-identical to today (needed for FR-006/SC-002 anyway).

## R2: Where the authoring level lives -- per `Prompt` or per `PromptSet`

**Decision**: On `PromptSet`, as one `level: int | None` field (default `None`). Not on individual
`Prompt`s.

**Rationale**: `PromptSet`'s own docstring already frames it as "a collection of prompts for one run
(single target structure)" -- the two real authoring paths (a hand-written/CLI-loaded prompt file, and
one `OrganMaskPredictor` session between `set_volume(level=...)` calls) each have exactly one active
level for their entire lifetime: `set_volume` resets `self._prompts = []` on every call, so every
`Prompt` an `OrganMaskPredictor` holds at `predict()` time was added under the same `self._level`.
Per-`Prompt` granularity would model a case (mixing prompts authored at different levels in one run)
that cannot occur through either entry point today, and the spec's FR-002 explicitly allows "per
prompt (or prompt set)".

`level=None` is the quiet, backward-compatible default for the many direct `PromptSet([...])`/
`Prompt(...)` constructions already in the test suite (benchmarks, unit tests, pipeline-internal
seed prompts for secondary sweep axes) that aren't going through either real authoring path and
should keep meaning exactly what they mean today: "these coordinates are already in the run level's
pixel grid." The conversion step (R3) treats `None` identically to "authoring level == run level":
identity, no-op.

**Alternatives considered**: Required `level` on every `Prompt`, defaulting to the run's own level --
rejected: it would force a mass, purely-mechanical edit of every internal/test `Prompt(...)` call site
in the codebase (pipeline-internal seed prompts included) for no behavioral benefit, since none of
those call sites represent a "saved, reused-later" prompt in the sense this feature is about.

## R3: The conversion itself (superseded by R8)

**Decision**: A `PromptSet` method taking the authoring level's shape, the target level's shape, and
the sweep-axis index, returning a new `PromptSet`:

- Identity (return `self`) when the two shapes are equal -- guarantees FR-006/SC-002's byte-identical
  same-level behavior without relying on `ratio == 1.0` arithmetic to be a true no-op.
- Otherwise, for each axis independently: `ratio = dst_shape[axis] / src_shape[axis]`; `frame_index`
  scales by the sweep axis's own ratio, `x`/box `x`-corners by the in-plane "width" axis's ratio, and
  `y`/box `y`-corners by the in-plane "height" axis's ratio -- using the exact same "the two axes
  other than `axis_index`, in index order -> (height, width)" convention `PromptSet.validate()`
  already uses, so the two stay consistent by construction.
- Rounds to the nearest pixel (`round`, not `floor`/`ceil`) -- the nearest-neighbor convention already
  used for mask resampling, applied here to a single coordinate rather than a whole array.

**Rationale**: Per-axis ratios (rather than a single scalar) are required because pyramids need not be
isotropic -- the sweep axis can be downsampled by a different factor than the in-plane axes (spec Edge
Cases). Reusing `validate()`'s own axis-ordering convention (rather than introducing a second one)
means the conversion and the validation it feeds into can never disagree about which shape index is
"height" vs. "width".

**Alternatives considered**: Deriving ratios from `coordinateTransformations` scale values instead of
shapes directly -- superseded by R1.

## R4: What happens when the authoring level doesn't exist in the current input (FR-008)

**Decision**: Before looking up the authoring level's shape, check it against the reader's actual
level count and raise a clear, actionable error (reusing `PromptError`, the same exception family
`PromptSet.validate()` already raises for prompt-data problems) naming the missing level and the
available ones (reusing the reader's existing `describe_levels()` helper, already used for the
analogous "run level doesn't exist" error in `io/reader.py::resolve_level`).

**Rationale**: Consistency with an error class already in the public contract (`PromptError`) and an
existing, already-tested "list what's actually available" message shape, rather than inventing a new
error type or message format for what is conceptually the same situation reader.py already handles
for the run level.

## R5: Keeping the on-disk/`to_record()` schema change minimal

**Decision**: `PromptSet.to_record()` changes shape from a bare `list[dict]` to `{"level": ...,
"objects": [...]}` -- i.e., the exact same shape as the (now `"level"`-bearing) input prompt-file
JSON. The only two consumers of the old shape are updated in lockstep: `engine/pipeline.py`'s
`record["prompts"] = prompts.to_record()` (unchanged call, naturally receives the new shape) and
`input_log.py::record_prompts()` (reads `record["objects"]` for the per-prompt lines it already
emits, plus one new `prompt_level: ...` line).

**Rationale**: Making the saved run-record's prompt section and the loadable prompt-file format
structurally identical is the simplest way to satisfy User Story 2 (a saved file's authoring level is
visible without computing anything) without introducing a second, differently-shaped representation.
Grep confirmed exactly two call sites read `to_record()`'s return value, so widening it is a two-line
change, not a wide-blast-radius one.

## R6: Existing tests that hand-write the old prompt-file format

**Decision**: All 14 files under `tests/` that currently write a bare `{"objects": [...]}` JSON
fixture (`test_prompts.py`, `test_frame_range.py`, `test_log_cli_failure.py`,
`test_log_cli_runid.py`, `test_log_cli.py`, `test_us5_postprocess.py`, `test_log_besteffort.py`,
`test_us6_interactive.py`, `test_us3_levels.py`, `test_log_options.py`, `test_log_prompts_cli.py`,
`test_api_cli_parity.py`, `test_log_stdout_clean.py`, `test_cli_mask.py`) must add the new required
`"level"` key or they will start failing under FR-007 (by design -- that rejection *is* the feature).

**Rationale/recommendation for tasks**: introduce one small shared helper in `tests/conftest.py`
(e.g. `write_prompt_file(path, objects, level=0)`) and have the mechanical edits go through it, rather
than repeating the same dict-literal fix in 14 places -- keeps the one-time mechanical change itself
reviewable as a single small diff pattern instead of 14 independent ones (Constitution I).
*Outcome*: not adopted -- most of the 14 files already route through their own local helper, so
adding `"level"` in place was the smaller change; the shared helper was dropped as unused.

## R7: Anisotropic pyramid test fixture

**Decision**: Extend `tests/conftest.py::write_ome_zarr` with an optional per-axis downsample-factor
argument (default: today's uniform `2` on every axis, so every existing caller is unaffected) so a
test can build a pyramid where the sweep axis and the in-plane axes are downsampled by different
factors -- the only way to exercise FR-004's per-axis-ratio requirement meaningfully, since a uniform
pyramid can't distinguish "correct per-axis conversion" from "a single scalar ratio happened to work."

**Rationale**: Without this, the anisotropic path in R3 would be implemented but untestable --
violating Constitution II (every behavioral change backed by a test that can actually fail).

## R8: Rework (2026-10-16) -- physical mapping, shared with feature 009

**Decision**: Replace the shape-ratio conversion (R1/R3) with physical mapping. Each coordinate goes
to its physical position on the authoring level (`i * scale + translation`, from the level's
OME-Zarr `coordinateTransformations`; scale 1 and translation 0 when absent). It then snaps to the
nearest pixel centre on the run level, with exact ties to the lower pixel. The formula lives in
`src/ome_zarr_masker/geometry.py::nearest_index`, so feature 009's mask writer can reuse it.
`OmeZarrReader.level_transform(level)` exposes each level's `(scale, translation)`.
`PromptSet.resolved_for_shape(src_shape, dst_shape, axis)` became
`PromptSet.resolved_between(src_geometry, dst_geometry, axis)`, vectorised across all prompts
(one call per axis).

**Rationale**:
- Feature 009 measured the shape-ratio approach against the real DANDI 001278 pyramid (half-pixel
  translations `(scale_N - scale_0)/2`, non-exact shape ratios such as 874 -> 1747). It was off by
  one pixel on 6-25% of planes at the finer levels.
- The R1 concern ("a second mechanism that disagrees with the writer") is resolved the other way
  around: the writer itself moves to physical mapping (009 FR-006), so prompts and mask share one
  rule.
- For translation-free pyramids with exact ratios (this repo's fixtures), results are unchanged
  except at exact ties. There, the old round-half-to-even picked the even pixel and the new rule
  picks the lower one (e.g. x = 15 at full resolution -> 7.5 -> 7, previously 8 and out of bounds).

**Consequences for tests**: the edge-case integration test that relied on that round-half-to-even
artifact (15 -> 8, out of bounds) now forces a genuinely out-of-bounds conversion by shifting the
run level's translation. The tie case itself is a unit test (x = 15 -> 7, in bounds).
