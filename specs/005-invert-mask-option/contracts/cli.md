# CLI Contract Delta: Invert Mask Output Option

Extends [specs/001-ome-zarr-sam-masking/contracts/cli.md](../../001-ome-zarr-sam-masking/contracts/cli.md).
All clauses in that document, and in the deltas from features 002–004, are unaffected and carry
over unchanged.

## New clauses

- **C-CLI-7**: `organ-masker-lite mask ... --invert` (no argument, default off) swaps the final
  output mask's binary values: background voxels become `1` and organ voxels become `0` (FR-001,
  FR-003, FR-006). It is applied after `--combine`, `--fill-holes`, `--dilate`, and `--erode`, so
  those flags always shape the organ-labeled region regardless of `--invert` (FR-004).
- **C-CLI-8**: `organ-masker-lite mask --help` output MUST include a description of `--invert`
  (FR-007).
- **C-CLI-9**: `organ-masker-lite interactive` does not accept `--invert`. Passing it there MUST
  fail immediately with `argparse`'s standard "unrecognized arguments" error and a non-zero exit
  code (FR-008).

## Unchanged clause, restated for clarity

- Without `--invert`, `organ-masker-lite mask` output is bit-for-bit identical to its current
  behavior (organ voxels `1`, background voxels `0`) — `--invert` adds a new opt-in code path, it
  does not alter the existing default path (FR-002).
