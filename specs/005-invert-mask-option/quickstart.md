# Quickstart: Validate Invert Mask Output Option

Prerequisites: repo checked out, `pip install -e ".[dev,sam2]"`. Steps 2-3 require a GPU with SAM2
weights available (e.g., this project's HPC GPU nodes); run them there. Run all commands from the
repo root.

## 1. Confirm `--invert` is documented and scoped correctly

```sh
organ-masker-lite mask --help | grep -A1 invert
organ-masker-lite interactive --help | grep invert
echo "exit: $?"
```

Expected: `mask --help` shows a description of `--invert` (C-CLI-8); `interactive --help` has no
`invert` match (grep exits non-zero) — the flag does not exist on that subcommand (C-CLI-9).

```sh
organ-masker-lite interactive <input.ome.zarr> --invert
echo "exit: $?"
```

Expected: non-zero exit, `argparse`'s standard "unrecognized arguments: --invert" message.

## 2. Confirm inverted output is the exact complement of non-inverted output

```sh
organ-masker-lite mask <input.ome.zarr> out_normal.ome.zarr --prompts <prompts.json> --level 0
organ-masker-lite mask <input.ome.zarr> out_inverted.ome.zarr --prompts <prompts.json> --level 0 --invert
```

```python
import numpy as np
from organ_masker_lite.io.reader import OmeZarrReader

normal = np.asarray(OmeZarrReader("out_normal.ome.zarr").read_level(0))
inverted = np.asarray(OmeZarrReader("out_inverted.ome.zarr").read_level(0))

assert normal.dtype == inverted.dtype == np.uint8          # FR-005: same on-disk encoding
assert np.array_equal(inverted, 1 - normal)                 # SC-001: exact voxel-wise complement
```

Expected: both assertions pass. Validates FR-001–FR-003, FR-005, SC-001.

## 3. Confirm morphology still shapes the organ region, not the inverted background

```sh
organ-masker-lite mask <input.ome.zarr> out_dilate_inverted.ome.zarr --prompts <prompts.json> \
  --level 0 --dilate 2 --invert
organ-masker-lite mask <input.ome.zarr> out_dilate_normal.ome.zarr --prompts <prompts.json> \
  --level 0 --dilate 2
```

```python
dilate_normal = np.asarray(OmeZarrReader("out_dilate_normal.ome.zarr").read_level(0))
dilate_inverted = np.asarray(OmeZarrReader("out_dilate_inverted.ome.zarr").read_level(0))

assert np.array_equal(dilate_inverted, 1 - dilate_normal)   # invert applied after dilation, FR-004
```

Expected: passes — the dilated organ region is identical either way; only the final polarity
differs. Validates FR-004.

## 4. Confirm omitting `--invert` leaves existing behavior untouched

```sh
pytest tests/contract/test_cli_mask.py tests/integration/test_us5_postprocess.py -q
```

Expected: full pass (with the usual `real_backend` skips on a machine without a GPU). Validates
FR-002/SC-002 — no regression for runs that don't pass `--invert`.

## 5. Confirm the new fast unit coverage runs without a GPU

```sh
pytest tests/unit/test_morphology.py -q
```

Expected: passes on any machine, no `real_backend` skip needed — this is the deterministic,
GPU-free test of the invert step and its ordering (Constitution Principle II).
