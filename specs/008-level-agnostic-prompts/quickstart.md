# Quickstart: Validate Level-Agnostic Prompt Coordinates

Prerequisites: repo checked out, `pip install -e ".[dev,sam2]"`. All steps are automatable (no
display needed); this feature touches only the headless engine/CLI/API.

## 1. Author a prompt at one level, rerun at another, same result (User Story 1, SC-001)

Using the `single_blob_zarr` fixture's convention (level 0 shape `(8, 16, 16)`, blob centered at
`(8, 8)` on frame `z=4`; coarsest level 1 has shape `(4, 8, 8)`, same blob centered at `(4, 4)` on
frame `z=2`):

```json
{"level": 0, "objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}]}
```

```sh
ome-zarr-masker mask input.ome.zarr out_level0.ome.zarr --prompts p.json --level 0
ome-zarr-masker mask input.ome.zarr out_level1.ome.zarr --prompts p.json --level 1
```

Expected: both succeed and both masks have non-empty foreground around the blob at their respective
level's grid -- `out_level1`'s mask is not empty/mislocated even though `p.json`'s coordinates were
authored at level 0. Compare against running with a *level-1-authored* prompt file
(`{"level": 1, ..., "xy": [4, 4], "frame": 2}`) directly at `--level 1`: the two `out_level1` results
should agree. Validates C-PF-1.

## 2. Same-level reruns are unchanged (FR-006, SC-002)

```sh
ome-zarr-masker mask input.ome.zarr out_a.ome.zarr --prompts p.json --level 0
ome-zarr-masker mask input.ome.zarr out_b.ome.zarr --prompts p.json --level 0
```

Expected: `out_a` and `out_b` are byte-identical (modulo the run-record's `run_id`), matching
pre-feature behavior exactly. Validates C-PF-2.

## 3. Old-format and unknown-level files are rejected, not silently misread (FR-007/FR-008, SC-004)

```sh
echo '{"objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}]}' > old.json
ome-zarr-masker mask input.ome.zarr out.ome.zarr --prompts old.json --level 0
echo $?   # expect 1, out.ome.zarr not created

echo '{"level": 99, "objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}]}' > badlevel.json
ome-zarr-masker mask input.ome.zarr out.ome.zarr --prompts badlevel.json --level 0
echo $?   # expect 1, error names available levels, out.ome.zarr not created
```

Expected: both exit non-zero with an actionable message, and neither leaves a partial `out.ome.zarr`
(mirrors the existing C-CLI-4 no-partial-output guarantee). Validates C-PF-3, C-PF-4.

## 4. Anisotropic pyramid: each axis converts by its own scale (Acceptance Scenario 3, FR-004)

```python
from ome_zarr_masker.config import RunConfig
from ome_zarr_masker.engine.pipeline import compute_mask
from ome_zarr_masker.prompts.model import Prompt, PromptSet
from tests.conftest import write_ome_zarr
import numpy as np

vol = np.zeros((8, 16, 16), np.uint8)
vol[2:6, 4:12, 4:12] = 200
# sweep axis (z) downsampled by 2x per level like today; in-plane axes (y, x) downsampled by 4x
store = write_ome_zarr(tmp_path / "aniso.ome.zarr", vol, axis_factors=(2, 4, 4))

prompts = PromptSet([Prompt(frame_index=4, point_coords=[[8, 8]], point_labels=[1])], level=0)
comp = compute_mask(store, prompts, RunConfig(axes=["z"], level=1))
assert comp.consensus.any()  # located correctly at level 1's (2, 4, 4)-shaped grid
```

Expected: the converted frame index and in-plane coordinates land on the blob even though the sweep
axis and in-plane axes scale by different factors between levels. Validates C-PF-6.

## 5. Automated test suite

```sh
pytest tests/unit/test_prompts.py -q
pytest tests/integration/test_us3_levels.py -q -m real_backend
```

Expected: unit tests cover conversion math, identity/no-op for same-level and unset `level`,
old-format rejection, and unknown-authoring-level rejection; the integration test covers the
end-to-end cross-level CLI scenario from Step 1 against the real SAM2 backend.
