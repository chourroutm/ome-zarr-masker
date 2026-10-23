# Data Model: Ordered Post-Processing Pipeline

All new types live in `src/ome_zarr_masker/postprocess/steps.py` unless noted. Immutable.

## Radius

| Field | Type | Meaning |
|-------|------|---------|
| `value` | float | Positive number as given. |
| `unit` | `str \| None` | `None` (run-level voxels) or one of `nm`, `um`, `mm`, `cm`, `m` (`µm` normalised to `um`). |
| `text` | str | The radius as the user wrote it (for records and messages). |

Rules (`PostProcessError`): value ≤ 0, not a number, or unknown unit → rejected (research R2).

## PostProcessStep

| Field | Type | Meaning |
|-------|------|---------|
| `op` | `"fill" \| "close" \| "open" \| "dilate" \| "erode" \| "largest" \| "margin" \| "invert"` | The operation. |
| `radius` | `Radius \| None` | Required for close/open/dilate/erode/margin; forbidden for fill/largest/invert. |

`str(step)` gives the step back in the shared notation (`close:3`, `margin:200um`).

## PostProcessSpec

What the user asked for, before it is resolved against a store.

| Field | Type | Meaning |
|-------|------|---------|
| `steps` | `tuple[PostProcessStep, ...] \| None` | `None` means the keyword `default` (inherit). `()` means no steps (`none`, or an empty list). |
| `source` | `"cli" \| "file" \| "prompt_file" \| "none" \| "default" \| "api"` | Where the steps came from (research R5). |

Functions:

- `parse_steps(value: str | Sequence[str] | None) -> PostProcessSpec` — the notation of
  `contracts/postprocess-notation.md`; `None`/`"default"` → `steps=None`.
- `load_postprocess_file(path) -> PostProcessSpec` — JSON object with a `"postprocess"` list.
- `PostProcessSpec.inherit(saved: tuple[PostProcessStep, ...] | None) -> PostProcessSpec` —
  resolves `default` against a prompt file's saved steps.

## ResolvedStep

A step with its radius in voxels for one run level (research R2–R3).

| Field | Type | Meaning |
|-------|------|---------|
| `step` | `PostProcessStep` | As given. |
| `radius_voxels` | `tuple[float, ...] \| None` | Per-axis voxel radius (axes order of the store). |
| `sampling` | `tuple[float, ...] \| None` | Per-axis voxel size used for the distance computation (voxel units: all 1). |

`resolve_steps(steps, scale, axis_units) -> tuple[ResolvedStep, ...]` raises `PostProcessError`
for a physical radius on axes without a length unit, or a radius < 1 voxel on every axis.
`to_record()` → `{"op", "radius", "radius_voxels"}`.

## Changes to existing types

- `config.PostProcessConfig`: **removed**. `RunConfig.postprocess: PostProcessSpec` (default:
  `default`, source `default`). `RunConfig.to_record()["postprocess"]` becomes
  `{"source", "steps": [ResolvedStep.to_record(), ...]}` once resolved (research R7).
- `postprocess.morphology.postprocess_mask(mask, config)` → `apply_steps(mask, resolved,
  *, workers=None) -> np.ndarray` (research R3–R4).
- `prompts.model.PromptSet`: new field `postprocess: tuple[PostProcessStep, ...] | None = None`
  (saved steps from a prompt file). `load_prompt_file` reads the optional `"postprocess"` key;
  new `save_prompt_file(path, prompt_set)` writes the feature 008 format plus `"postprocess"`.
- `io.reader.OmeZarrReader`: new `axis_units: list[str | None]`.
- `io.writer`: output axes carry the input's units (FR-013).
- `InteractiveSession`: new state `postprocess: PostProcessSpec` (panel value) and
  `prompts_path: Path`; methods `set_postprocess(value)`, `save_prompts(path=None)`; prompts are
  loaded from `prompts_path` when it exists (converted to the session level, feature 008).

## Resolution flow (one run)

```text
CLI/API/session value ──parse──▶ PostProcessSpec ──inherit(prompt file saved steps)──▶ steps
     │                                                                               │
     └──────────── PostProcessError before segmentation ◀──resolve(scale, units)─────┘
                                                                ▼
                         consensus ──apply_steps (in order)──▶ mask ──▶ writer (all levels)
```
