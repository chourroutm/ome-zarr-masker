# Contract: Command-Line Interface

**Feature**: 001-ome-zarr-sam-masking | **Date**: 2026-06-14

One-shot, non-interactive CLI (FR-008) built on stdlib `argparse`. Invoked as `ome-zarr-masker`
(console script) or `python -m ome_zarr_masker`.

## `ome-zarr-masker mask`

Run end-to-end masking from an input volume and a prompt file to an OME-Zarr v0.5 mask.

```
ome-zarr-masker mask INPUT OUTPUT --prompts PROMPTS [options]
```

### Arguments

| Arg | Required | Default | Description |
|-----|----------|---------|-------------|
| `INPUT` | yes | - | Path to input OME-Zarr v0.5 store |
| `OUTPUT` | yes | - | Path to output OME-Zarr v0.5 store |
| `--prompts PATH` | yes | - | Prompt file (points/labels/box) |
| `--backend {sam2,sam3}` | no | `sam2` | Segmentation backend (FR-018) |
| `--level INT` | no | coarsest level (highest index) | Multiscale level to run on (FR-003) |
| `--axes AXES` | no | single axis | Comma-separated sweep axes, e.g. `z` or `z,y,x` (FR-007) |
| `--direction {forward,forward_reverse}` | no | `forward` | Propagation mode (FR-006) |
| `--combine {majority,union,intersection}` | no | `majority` | Consensus rule (FR-007) |
| `--fill-holes / --no-fill-holes` | no | on | Hole filling (FR-012) |
| `--dilate INT` | no | `0` | Dilation radius (FR-012) |
| `--erode INT` | no | `0` | Erosion radius (FR-012) |
| `--model-dir PATH` | no | `./ome_zarr_masker_models` (or env) | Weights directory (FR-019) |
| `--no-download` | no | download on | Disable weight auto-download (FR-020) |
| `--overwrite` | no | off | Allow overwriting existing OUTPUT (FR-013) |
| `--workers INT` | no | automatic | Output shards written in parallel, ≥ 1 (feature 009; see `specs/009-scalable-mask-writer/contracts/cli.md`) |
| `--verbose` | no | off | More logging |

### Prompt file format

A small text format (JSON) listing prompts; mirrors the API convention:
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
- `level` (**required**, as of feature 008-level-agnostic-prompts): the pyramid level these
  coordinates were read off of. It need not match this run's own `--level` -- coordinates are
  automatically converted to whichever level the run actually uses. A file with no `level` key
  (the pre-008 format) is rejected with a clear error, never silently reinterpreted; see
  `specs/008-level-agnostic-prompts/contracts/prompt-file-format.md`.
- `label`: `1` positive, `0` negative/exclusion (SAM2 convention).
- `box` optional; at least one positive point or a box is required overall (FR-015).

### Exit codes & output behavior

| Code | Meaning |
|------|---------|
| `0` | Success; OUTPUT written as valid OME-Zarr v0.5 with same levels as INPUT |
| `2` | Usage error (argparse) |
| `1` | Runtime error: invalid OME-Zarr, missing level, invalid/out-of-bounds prompts, missing weights with `--no-download`, or existing OUTPUT without `--overwrite` |

- Progress is reported for long operations (FR-017).
- On error, no partial OUTPUT store is left behind (FR-013).
- The run parameters and prompts are recorded alongside OUTPUT (FR-014).

## `ome-zarr-masker interactive` (P4)

Launches the napari session (requires the `[interactive]` extra). Shares the same engine and writes
the same OME-Zarr v0.5 output on export (FR-009, FR-011).

## Behavioral contract (testable)

- C-CLI-1: `mask` on a valid input with a single-positive-point prompt file writes a valid OME-Zarr
  v0.5 OUTPUT whose level count equals INPUT's (SC-001, SC-002). *(first feature to test)*
- C-CLI-2: A box prompt file produces foreground within the box. *(second feature to test)*
- C-CLI-3: An exclusion point (label 0) removes the excluded region. *(third feature to test)*
- C-CLI-4: Invalid input store, missing level, empty/positive-less prompts, out-of-bounds prompt,
  existing OUTPUT without `--overwrite`, or `--no-download` with missing weights each exit non-zero
  with a clear message and leave no partial OUTPUT (FR-013, FR-015, SC-009).
- C-CLI-5: `--backend sam3` runs the same pipeline (SC-010).
- C-CLI-6: CLI and API outputs match for identical inputs/prompts (SC-005).
