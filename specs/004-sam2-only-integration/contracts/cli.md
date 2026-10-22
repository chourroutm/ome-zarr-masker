# CLI Contract Delta: SAM2-Only Integration

Supersedes the `--backend` clauses of
[specs/001-ome-zarr-sam-masking/contracts/cli.md](../../001-ome-zarr-sam-masking/contracts/cli.md).
All other clauses in that document are unchanged by this feature.

## Removed clause

- ~~`--backend {sam2,sam3}` (no, default `sam2`): Segmentation backend (FR-018)~~ — the flag is
  removed entirely from both the `mask` and `interactive` subcommands. There is no replacement flag,
  boolean or otherwise. SAM2 always runs.
- ~~C-CLI-5: `--backend sam3` runs the same pipeline (SC-010).~~ Removed — no backend selection exists.

## New clause

- **C-CLI-6**: `ome-zarr-masker mask ... --backend <anything>` (or `interactive ... --backend
  <anything>`) MUST fail immediately with `argparse`'s standard "unrecognized arguments" error and a
  non-zero exit code, since `--backend` is not a recognized flag (FR-004).
