# organ-masker-lite

Mask organs in OME-Zarr v0.5 volumes with SAM2. Place a few landmarks on a single plane, and
organ-masker-lite propagates them across the volume -- treating each axis sweep as a "video" of
slices for SAM2 -- and writes a single binary OME-Zarr v0.5 mask whose pyramid matches the input's
levels.

Three entry points share one engine (CLI, Python API, interactive napari session), so they produce
identical results for identical inputs.

## Features

- OME-Zarr v0.5 in, OME-Zarr v0.5 mask out, validated in-process by the bundled `ome-zarr-models`.
- SAM2 is the only, unconditional segmentation backend -- nothing to select or configure.
- Single- or multi-axis sweeps with forward or forward-and-reverse propagation; majority / union /
  intersection consensus. In multi-axis runs you prompt one plane and the other axes are seeded
  automatically.
- Pick any pyramid (binning) level; the coarsest level is the default and is faster.
- Optional morphological post-processing (fill-holes on by default; dilation/erosion off).
- SAM-like Python API and an interactive napari session.
- Out-of-core intermediates (on-disk memmap frame stack and vote accumulator) keep RAM bounded.
- Every output embeds a `run_record.json` for reproducibility (see [docs/run-record.md](docs/run-record.md)).

## Install

Python 3.11+.

```bash
pip install -e ".[sam2]"                 # SAM2 (torch + sam2)
pip install -e ".[interactive]"          # optional napari viewer
pip install -e ".[dev]"                  # tests + linting
```

OME-Zarr v0.5 input validation is provided by the bundled `ome-zarr-models` dependency and runs
in-process, so a plain install is enough -- no validator command needs to be on your `PATH`. A CUDA
GPU (>= 8 GB) is recommended; weights auto-download into `./organ_masker_models` on first use
(override with `--model-dir` / `ORGAN_MASKER_MODEL_DIR`, or use `--no-download` with pre-placed
weights for offline use).

## CLI

```bash
organ-masker-lite mask INPUT OUTPUT --prompts PROMPTS [options]
```

Single positive point:

```bash
cat > prompts.json <<'JSON'
{"objects":[{"obj_id":0,"points":[{"frame":120,"xy":[340,512],"label":1}]}]}
JSON

organ-masker-lite mask input.ome.zarr output.ome.zarr \
  --prompts prompts.json --level 3 --axes z --direction forward
```

Key options:

| Option | Default | Meaning |
|--------|---------|---------|
| `--level INT` | coarsest | Pyramid level to run on. |
| `--axes AXES` | `z` | Comma-separated sweep axes; the first is the prompted axis. |
| `--direction {forward,forward_reverse}` | `forward` | Propagation mode. |
| `--combine {majority,union,intersection}` | `majority` | Consensus across sweeps. |
| `--fill-holes / --no-fill-holes` | on | Fill interior holes. |
| `--dilate INT` / `--erode INT` | `0` | Morphology radii (voxels). |
| `--overwrite` | off | Replace an existing output. |
| `--log-dir PATH` | `./organ_masker_logs` | Directory for per-invocation input logs. |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | `INFO` | Verbosity of ancillary log messages. |

### Prompt file

```json
{
  "objects": [
    {
      "obj_id": 0,
      "points": [{"frame": 120, "xy": [340, 512], "label": 1}],
      "box": {"frame": 120, "xyxy": [300, 480, 380, 560]}
    }
  ]
}
```

`label` is `1` for a positive (include) point and `0` for a negative (exclude) point. At least one
positive point or a box is required.

### Input logging

Every invocation -- CLI or API -- writes one plain-text log file to `<log-dir>/<run-id>.log`
capturing the command, parsed options, resolved effective configuration, and the full prompt set.
The log is written before validation, so runs that fail before producing output are still recorded,
with an `outcome:` line on exit. The log's `run_id` matches the `run_id` embedded in the output's
`run_record.json`, correlating each log with its mask.

The default directory is `./organ_masker_logs` (override with `--log-dir` or the
`ORGAN_MASKER_LOG_DIR` environment variable). Logging is best-effort and never touches stdout: if
the log cannot be written (e.g. an unwritable `--log-dir`), the masking run still completes and a
single warning is printed to stderr.

## Python API

The API mirrors the SAM/SAM2 predictor structure:

```python
from organ_masker_lite import OrganMaskPredictor

p = OrganMaskPredictor()
p.set_volume("input.ome.zarr", level=3)            # mirrors SAM set_image
p.add_points(frame_index=120, point_coords=[[340, 512]], point_labels=[1])
mask = p.predict(axes=["z"], direction="forward")  # returns a MaskResult
mask.save("api_out.ome.zarr")
```

`add_box(frame_index, box=[x0, y0, x1, y1])` adds a box; both prompt methods may be combined. The
saved output equals the CLI output for identical inputs/prompts.

`predict(...)` logs the run just like the CLI (with `prompt_source="api"`); pass
`OrganMaskPredictor(..., log_dir=..., log_level=...)` to control the destination and verbosity, and
read `mask.run_id` to correlate the result with its log file and saved `run_record.json`.

## Interactive session

```bash
pip install -e ".[interactive]"
organ-masker-lite interactive input.ome.zarr --level 3
```

Place landmarks on the points layer, press `p` to preview the mask and `e` to export it. The session
runs on the same engine as the CLI and API.

## Development

```bash
pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests
pytest                       # add -m "not slow" to skip the timing/benchmark tests
```

Tests that exercise real segmentation are marked `real_backend` and are skipped unless torch + sam2
(and, for the interactive smoke test, napari) are installed and a GPU with SAM2 weights is
available. There is no CPU-only stand-in; these tests verify the actual, shipped SAM2 path.
