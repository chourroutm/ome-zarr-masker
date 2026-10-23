# ome-zarr-masker

Mask organs in OME-Zarr v0.5 volumes with SAM2. Place a few landmarks on a single plane, and
ome-zarr-masker propagates them across the volume -- treating each axis sweep as a "video" of
slices for SAM2 -- and writes a single binary OME-Zarr v0.5 mask whose pyramid matches the input's
levels.

Three entry points share one engine (CLI, Python API, interactive napari session), so they produce
identical results for identical inputs.

> Formerly `organ-masker-lite`. The package (`ome_zarr_masker`), command (`ome-zarr-masker`),
> environment variables (`OME_ZARR_MASKER_*`) and default directories (`./ome_zarr_masker_models`,
> `./ome_zarr_masker_logs`) were renamed; move existing `./organ_masker_models` weights to the new
> directory (or pass `--model-dir`) to avoid re-downloading them.

## Features

- OME-Zarr v0.5 in, OME-Zarr v0.5 mask out, validated in-process by the bundled `ome-zarr-models`.
- SAM2 is the only, unconditional segmentation backend -- nothing to select or configure.
- Single- or multi-axis sweeps with forward or forward-and-reverse propagation; majority / union /
  intersection consensus. In multi-axis runs you prompt one plane and the other axes are seeded
  automatically.
- Pick any pyramid (binning) level; the coarsest level is the default and is faster.
- Ordered post-processing (`--postprocess close:3,fill,largest,margin:200um`): closing, opening,
  dilation, erosion, hole filling, largest component, margin and inversion, in the order you give,
  with radii in voxels or physical units (see [Post-processing](#post-processing)).
- SAM-like Python API and an interactive napari session.
- Out-of-core intermediates (on-disk memmap frame stack and vote accumulator) keep RAM bounded.
- Masks are written shard by shard, compressed, in bounded memory -- even for full-resolution levels
  far larger than RAM (see [Output](#output)).
- Every output embeds a `run_record.json` for reproducibility (see [docs/run-record.md](docs/run-record.md)).
- Inputs and outputs can be remote: read over HTTP(S), read and write S3, Google Cloud Storage and
  Azure Blob Storage, fetching only the level a run needs (see [Remote stores](#remote-stores)).

## Install

Python 3.11+.

```bash
pip install -e ".[sam2]"                 # SAM2 (torch + sam2)
pip install -e ".[interactive]"          # optional napari viewer
pip install -e ".[dev]"                  # tests + linting
pip install -e ".[remote]"               # remote stores: or just [s3], [gcs], [azure], [http]
```

OME-Zarr v0.5 input validation is provided by the bundled `ome-zarr-models` dependency and runs
in-process, so a plain install is enough -- no validator command needs to be on your `PATH`. A CUDA
GPU (>= 8 GB) is recommended; weights auto-download into `./ome_zarr_masker_models` on first use
(override with `--model-dir` / `OME_ZARR_MASKER_MODEL_DIR`, or use `--no-download` with pre-placed
weights for offline use).

## CLI

```bash
ome-zarr-masker mask INPUT OUTPUT --prompts PROMPTS [options]
```

Single positive point:

```bash
cat > prompts.json <<'JSON'
{"level":3,"objects":[{"obj_id":0,"points":[{"frame":120,"xy":[340,512],"label":1}]}]}
JSON

ome-zarr-masker mask input.ome.zarr output.ome.zarr \
  --prompts prompts.json --level 3 --axes z --direction forward
```

Key options:

| Option | Default | Meaning |
|--------|---------|---------|
| `--level INT` | coarsest | Pyramid level to run on. |
| `--axes AXES` | `z` | Comma-separated sweep axes; the first is the prompted axis. |
| `--direction {forward,forward_reverse}` | `forward` | Propagation mode. |
| `--combine {majority,union,intersection}` | `majority` | Consensus across sweeps. |
| `--postprocess STEPS` | `default` | Ordered post-processing steps (see [Post-processing](#post-processing)); `default` uses the prompt file's saved steps, or none. |
| `--postprocess-file FILE` | | Read the steps from a JSON file instead (`{"postprocess": [...]}`). |
| `--overwrite` | off | Replace an existing output. |
| `--workers INT` | automatic | Output shards written in parallel (default: as many as fit in an 8 GiB write budget, at most the CPU count). |
| `--log-dir PATH` | `./ome_zarr_masker_logs` | Directory for per-invocation input logs. |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | `INFO` | Verbosity of ancillary log messages. |

### Prompt file

```json
{
  "level": 3,
  "objects": [
    {
      "obj_id": 0,
      "points": [{"frame": 120, "xy": [340, 512], "label": 1}],
      "box": {"frame": 120, "xyxy": [300, 480, 380, 560]}
    }
  ]
}
```

`level` is the pyramid level these coordinates were read off of -- it is required, and need not
match the `--level` the run itself uses: coordinates are automatically converted to whichever level
`mask` actually runs at. `label` is `1` for a positive (include) point and `0` for a negative
(exclude) point. At least one positive point or a box is required.

`frame` is a plane along the first `--axes` axis, and points may sit on several frames. In
multi-axis runs, a sweep can briefly lose the object for a few frames and leave thin planes of
missing voxels; placing prompts on several frames spread through the object (and adding `close` to
the post-processing) reduces these dropouts.

An optional `"postprocess"` list saves post-processing steps with the prompts (the interactive
session writes it when you save); `mask` uses them unless `--postprocess` or `--postprocess-file`
says otherwise:

```json
{"level": 3, "objects": [...], "postprocess": ["close:3", "fill", "largest", "margin:200um"]}
```

### Post-processing

The mask computed at the run level can be cleaned up by a sequence of steps, applied in the order
given, each to the result of the previous one:

| Step | Effect |
|------|--------|
| `fill` | Fill 3D holes (cavities not connected to the volume border). |
| `close:R` | Dilate then erode by R: closes gaps narrower than about 2R. Never removes mask voxels, even where the sample touches the volume edge. |
| `open:R` | Erode then dilate by R: removes parts thinner than about 2R. Never adds mask voxels. |
| `dilate:R` / `margin:R` | Add every voxel within distance R of the mask (the two are the same). |
| `erode:R` | Remove every mask voxel within distance R of the background (outside the volume counts as background). |
| `largest` | Keep the largest connected component (voxels touching by a face, edge or corner are connected). |
| `invert` | Swap mask and background; steps after it act on the inverted mask, so put it last to invert the final result. |

`R` is a number of run-level voxels (`close:3`), or a length with a unit -- `nm`, `um` (or `µm`),
`mm`, `cm`, `m` (`margin:200um`, `close:0.2mm`). Physical radii are converted along each axis with
the run level's voxel size and the store's axis units, so the same command gives the same physical
clean-up at any `--level` and stays correct for non-cubic voxels; they need axis units in the
store's metadata. Neighbourhoods are balls (ellipsoids in voxels when voxels aren't cubic).

```bash
ome-zarr-masker mask input.ome.zarr output.ome.zarr --prompts prompts.json --level 3 \
  --axes z,y,x --direction forward_reverse --postprocess close:200um,fill,largest,margin:200um
```

Where the steps come from:

- `--postprocess STEPS` (comma separated) or `--postprocess-file FILE`, a JSON object with a
  `"postprocess"` list (a prompt file with saved steps works too); only one of the two.
- Otherwise (`--postprocess default`, the default) the steps saved in the prompt file, or no steps
  at all: hole filling only happens when `fill` is listed.
- `--postprocess none` applies no steps, even if the prompt file has some.

Invalid steps, radii or units fail before any segmentation. The run record lists the steps applied,
with each radius as given and in voxels per axis, and where they came from.

### Output

The output has the same levels, shapes, axes and coordinate transforms as the input. Each level is a
`uint8` 0/1 array stored as Zarr v3 shards with blosc (zstd, bitshuffle) compression and
`fill_value=0`, so background-only regions take no space:

- If the matching input level is sharded, its chunk and shard shapes are reused, so the mask lines up
  with the image (e.g. pyramids written by ome-zarr-tools).
- Otherwise each level uses 64³ chunks in shards of up to 1024³.

The mask is computed at the run level (`--level`) and resampled to every other level by physical
nearest neighbour: each output voxel takes the run-level voxel nearest to its centre, using each
level's scale and translation, so half-pixel-translated pyramids stay aligned. Writing never holds a
whole level in memory; it works shard by shard within an 8 GiB budget (`--workers` overrides the
parallelism). With `--verbose`, progress is reported per level. `run_record.json` lists each level's
layout under `output_layout`.

### Remote stores

`INPUT` and `OUTPUT` (and the Python API's store arguments) may be URLs instead of local paths:

```bash
ome-zarr-masker mask https://example.org/data/brain.ome.zarr mask.ome.zarr --prompts p.json
ome-zarr-masker mask s3://my-bucket/brain.ome.zarr s3://my-bucket/brain-mask.ome.zarr --prompts p.json
ome-zarr-masker mask gs://my-bucket/brain.ome.zarr mask.ome.zarr --prompts p.json
ome-zarr-masker mask az://container/brain.ome.zarr az://container/mask.ome.zarr --prompts p.json
```

| Form | Read | Write |
|------|------|-------|
| `s3://bucket/key`, `https://bucket.s3[.region].amazonaws.com/key`, `https://s3.region.amazonaws.com/bucket/key` | yes | yes |
| `gs://bucket/key`, `https://storage.googleapis.com/bucket/key` | yes | yes |
| `az://container/path`, `abfs://container@account.dfs.core.windows.net/path`, `https://account.blob.core.windows.net/container/path` | yes | yes |
| any other `http(s)://` URL | yes | no |

The full list is in
[specs/010-remote-store-support/contracts/store-location.md](specs/010-remote-store-support/contracts/store-location.md).
Anything without `<scheme>://` is a local path, exactly as before. Install the extra for each
provider you use: `[s3]`, `[gcs]`, `[azure]`, `[http]`, or `[remote]` for all of them.

- **Only what's needed is read**: the metadata and the selected level, never the whole store.
- **Credentials come from each provider's standard configuration**: S3 uses the AWS chain
  (environment, `AWS_PROFILE`/config files, instance role; `AWS_ENDPOINT_URL` for S3-compatible
  services); GCS uses application default credentials; Azure uses `AZURE_STORAGE_*` variables, a
  service principal or `az login` (for `az://`, set `AZURE_STORAGE_ACCOUNT_NAME`). With nothing
  configured, access is anonymous, so public data needs no setup. There are no credential flags,
  and URLs carrying credentials or signed query strings (`user:pass@`, `?sig=...`) are rejected, so
  no secret can reach a log or run record.
- **Writing** follows the local rules (`--overwrite` to replace an existing store). The root
  `zarr.json` is written last, so a failed write never reads as a valid store. Unlike a local
  output, a failed **remote overwrite** has already removed the previous store.
- Input and output naming the same remote store are rejected. Errors say whether a location was not
  found, access was denied or the network failed, separately from "not valid OME-Zarr v0.5".
- The interactive session reads remote inputs, but exports only to local paths; write remote output
  with `mask` or `MaskResult.save`.

### Input logging

Every invocation -- CLI or API -- writes one plain-text log file to `<log-dir>/<run-id>.log`
capturing the command, parsed options, resolved effective configuration, and the full prompt set.
The log is written before validation, so runs that fail before producing output are still recorded,
with an `outcome:` line on exit. The log's `run_id` matches the `run_id` embedded in the output's
`run_record.json`, correlating each log with its mask.

The default directory is `./ome_zarr_masker_logs` (override with `--log-dir` or the
`OME_ZARR_MASKER_LOG_DIR` environment variable). Logging is best-effort and never touches stdout: if
the log cannot be written (e.g. an unwritable `--log-dir`), the masking run still completes and a
single warning is printed to stderr.

## Python API

The API mirrors the SAM/SAM2 predictor structure:

```python
from ome_zarr_masker import OrganMaskPredictor

p = OrganMaskPredictor()
p.set_volume("input.ome.zarr", level=3)  # mirrors SAM set_image
p.add_prompts(frame_index=120, point_coords=[[340, 512]], point_labels=[1])
mask = p.predict(axes=["z"], direction="forward", postprocess="close:3,fill")  # a MaskResult
mask.save("api_out.ome.zarr")  # optional: workers=4, progress=print
```

`add_box(frame_index, box=[x0, y0, x1, y1])` adds a box; both prompt methods may be combined.
`postprocess` takes the steps of [Post-processing](#post-processing), as one string or a list
(default: none). The
saved output equals the CLI output for identical inputs/prompts. `MaskResult.save(path, overwrite=False,
*, workers=None, progress=None)` writes it shard by shard (see [Output](#output)); `workers` sets the
number of shards written in parallel and `progress` receives per-level messages, including the worker
count used.

`predict(...)` logs the run just like the CLI (with `prompt_source="api"`); pass
`OrganMaskPredictor(..., log_dir=..., log_level=...)` to control the destination and verbosity, and
read `mask.run_id` to correlate the result with its log file and saved `run_record.json`.

## Interactive session

```bash
pip install -e ".[interactive]"
ome-zarr-masker interactive input.ome.zarr --level 3 --prompts prompts.json --postprocess close:3,fill
```

Place landmarks on the points layer -- new points default to positive (green); select one or more
and press `n` to mark them negative/exclusion (red), or `y` to mark them positive again. Press `p`
to preview the mask and `e` to export it. The session runs on the same engine as the CLI and API.

The "Post-processing" panel holds the steps used by previews and exports, pre-filled from
`--postprocess`/`--postprocess-file` or from the steps saved in the prompt file; edit them and press
"Apply" (edits are also applied before each preview, export and save; an invalid edit is refused).
"Save prompts" (or `w`) writes the prompts and the panel's steps to `--prompts` (default
`prompts.json`), so `ome-zarr-masker mask ... --prompts prompts.json` reproduces the same clean-up.
An existing `--prompts` file is loaded when the session opens.
`INPUT` may be a remote URL (see [Remote stores](#remote-stores)); exports are local.

## Development

```bash
pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests
pytest                       # add -m "not slow" to skip the timing/benchmark tests
```

Tests that exercise real segmentation are marked `real_backend` and are skipped unless torch + sam2
(and, for the interactive smoke test, napari) are installed and a GPU with SAM2 weights is
available. There is no CPU-only stand-in; these tests verify the actual, shipped SAM2 path.

Remote-store tests run offline (a local HTTP server, moto's in-process S3 and an in-memory
filesystem). Tests against real buckets are marked `remote_live` and run only when
`OME_ZARR_MASKER_TEST_S3_URL`, `OME_ZARR_MASKER_TEST_GCS_URL` or `OME_ZARR_MASKER_TEST_AZURE_URL`
names a writable test prefix: `pytest -m remote_live`.
