# Contract: Post-processing notation

**Feature**: 011-ordered-postprocessing | **Date**: 2026-10-23

One notation for `--postprocess`, post-processing files, saved steps in prompt files, the Python
API and the interactive panel.

## Grammar

```text
sequence := keyword | step ("," step)*
keyword  := "default" | "none"
step     := op | op ":" radius
op       := "fill" | "close" | "open" | "dilate" | "erode" | "largest" | "margin" | "invert"
radius   := number [unit]          number > 0, decimals allowed
unit     := "nm" | "um" | "µm" | "mm" | "cm" | "m"
```

Case-insensitive; whitespace around `,` and `:` ignored. In JSON files the sequence is a list of
step strings (`["close:3", "fill"]`); keywords are not allowed in files (an empty list = no steps).

## Steps

| Step | Radius | Effect (on the current mask) |
|------|--------|------------------------------|
| `fill` | no | Fill 3D holes (background not connected to the volume border). |
| `dilate:R` | yes | Add every voxel within distance R of the mask. |
| `margin:R` | yes | Same as `dilate:R`. |
| `erode:R` | yes | Remove every mask voxel within distance R of background (outside the volume is background). |
| `close:R` | yes | Dilate then erode by R; never removes a mask voxel. |
| `open:R` | yes | Erode then dilate by R; never adds a mask voxel. |
| `largest` | no | Keep the largest 26-connected component; ties: first in scan order; empty stays empty. |
| `invert` | no | Swap mask and background; later steps act on the inverted mask. |

Distance R: run-level voxels without a unit; physical length with a unit, converted per axis
with the run level's scale and axis units (an ellipsoid in voxels when voxels are not cubic).

## Behavioural contract (testable)

- C-PP-1: Steps are applied in the order given; repeating a step applies it again.
- C-PP-2: Each step's result equals a direct reference computation (explicit ellipsoid structure
  over the whole volume; `binary_fill_holes`; 26-connected labelling), voxel for voxel.
- C-PP-3: A physical radius gives the same physical extent at any level, within one run-level
  voxel per axis (SC-002).
- C-PP-4: Rejected before segmentation, with a message naming the step: unknown op; missing or
  forbidden radius; radius ≤ 0 or not a number; unknown unit; `default`/`none` with other steps;
  physical radius on axes without a length unit; physical radius < 1 voxel on every axis.
- C-PP-5: `str(step)` round-trips: `parse_steps(",".join(map(str, steps)))` gives the same steps.
