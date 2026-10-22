# Quickstart & Validation Guide: OME-Zarr Organ Masking with SAM

**Feature**: 001-ome-zarr-sam-masking | **Date**: 2026-06-14

Runnable scenarios that prove the feature works end-to-end. Contracts and entities are referenced,
not duplicated (see [contracts/](./contracts/) and [data-model.md](./data-model.md)).

## Prerequisites

- Python 3.11+.
- Install the package with a backend extra:
  ```bash
  pip install -e ".[sam2]"        # default backend
  # optional: pip install -e ".[sam3]" ".[interactive]"
  ```
- `ome-zarr-models` is bundled as a dependency and performs input validation in-process; no
  validator command needs to be on PATH (feature 003).
- A small OME-Zarr v0.5 input store. Tests generate a synthetic one (see Test Data below); for
  manual runs, point at any v0.5 multiscale store.
- For real backends: a CUDA GPU is recommended; weights auto-download into `./ome_zarr_masker_models`
  on first run (use `--no-download` with pre-placed weights for offline/air-gapped use).

## Validate the environment

```bash
ome-zarr-masker --help
# Input validation runs in-process when you invoke `ome-zarr-masker mask`; no separate
# validator command is required.
```

## Scenario 1 — Single-point one-shot mask (US1, first feature to test)

Goal: image in, mask out, from a single positive point.

```bash
cat > prompts.json <<'JSON'
{"objects":[{"obj_id":0,"points":[{"frame":120,"xy":[340,512],"label":1}]}]}
JSON

ome-zarr-masker mask input.ome.zarr output.ome.zarr \
  --prompts prompts.json --backend sam2 --level 3 --axes z --direction forward
```

Expected:
- Exit code 0.
- `output.ome.zarr` is a valid OME-Zarr v0.5 store (validated in-process via `ome-zarr-models`).
- Output has the **same number of levels** as `input.ome.zarr`.
- Foreground includes the prompted location. (Contract C-CLI-1)

## Scenario 2 — Bounding-box prompt (US1, second feature to test)

```bash
cat > box.json <<'JSON'
{"objects":[{"obj_id":0,"box":{"frame":120,"xyxy":[300,480,380,560]}}]}
JSON

ome-zarr-masker mask input.ome.zarr out_box.ome.zarr --prompts box.json --level 3 --axes z
```

Expected: foreground lies predominantly within the box on the prompt frame. (C-CLI-2)

## Scenario 3 — Exclusion point (US1, third feature to test)

```bash
cat > exclude.json <<'JSON'
{"objects":[{"obj_id":0,"points":[
  {"frame":120,"xy":[340,512],"label":1},
  {"frame":120,"xy":[355,520],"label":0}
]}]}
JSON

ome-zarr-masker mask input.ome.zarr out_excl.ome.zarr --prompts exclude.json --level 3 --axes z
```

Expected: the region around the negative (label 0) point is excluded from the foreground. (C-CLI-3)

## Scenario 4 — Python API parity (US4)

```python
from ome_zarr_masker import OrganMaskPredictor

p = OrganMaskPredictor(backend="sam2")
p.set_volume("input.ome.zarr", level=3)
p.add_points(frame_index=120, point_coords=[[340, 512]], point_labels=[1])
p.predict(axes=["z"], direction="forward").save("api_out.ome.zarr")
```

Expected: `api_out.ome.zarr` equals the Scenario 1 CLI output for identical inputs/prompts. (C-API-6)

## Scenario 5 — Multi-axis, forward+reverse (US2)

```bash
ome-zarr-masker mask input.ome.zarr out_multi.ome.zarr --prompts prompts.json \
  --axes z,y,x --direction forward_reverse --combine majority
```

Expected: consensus mask agreement >= the single-axis forward-only result with the same prompts.
(SC-003)

## Scenario 6 — Backend comparison (SAM2 vs SAM3, US partial)

```bash
ome-zarr-masker mask input.ome.zarr out_sam2.ome.zarr --prompts prompts.json --backend sam2
ome-zarr-masker mask input.ome.zarr out_sam3.ome.zarr --prompts prompts.json --backend sam3
```

Expected: identical inputs/prompts, only the backend differs; both produce valid masks for
like-for-like comparison. (SC-010)

## Scenario 7 — Error handling (SC-009)

```bash
ome-zarr-masker mask not_a_zarr output.ome.zarr --prompts prompts.json   # invalid input
ome-zarr-masker mask input.ome.zarr output.ome.zarr --prompts empty.json # no positive prompt
ome-zarr-masker mask input.ome.zarr output.ome.zarr --prompts prompts.json --level 999  # bad level
```

Expected: each exits non-zero with a clear message; no partial `output.ome.zarr` is created.

## Test Data

- Integration tests synthesize a tiny multiscale OME-Zarr v0.5 volume containing a known foreground
  blob, plus prompts targeting it, so assertions on overlap and exclusion are deterministic.
- Engine/unit tests use a deterministic **stub backend** (no torch/weights) so the sweep,
  combination, IO, prompt-validation, and pyramid-matching logic are tested without a GPU.

## Performance check (Principle IV)

- A benchmark runs Scenario 1 on the reference volume and asserts the targets in
  [plan.md](./plan.md) (runtime budget on GPU; peak host RAM under the ceiling and independent of
  slice count; coarser level faster than finer, SC-006).
