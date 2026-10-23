# Run record (reproducibility)

Every mask written by ome-zarr-masker embeds a `run_record.json` at the root of the output
OME-Zarr v0.5 store. It captures the full, reproducible parameterization of the run -- the input,
the level, the configuration, and the prompts -- so a result can be audited and re-created
(FR-014). The CLI, the Python API, and the interactive session all write the same record, because
they share one engine.

## Location

```
output.ome.zarr/
├── zarr.json            # OME-Zarr v0.5 multiscale metadata
├── 0/ 1/ ...            # mask pyramid levels (uint8 0/1, sharded + compressed, same levels as the input)
└── run_record.json      # this record
```

## Fields

| Field | Type | Meaning |
|-------|------|---------|
| `run_id` | string | Identifier of this invocation; matches the input log `<log-dir>/<run_id>.log`. |
| `input` | string | The input OME-Zarr v0.5 store: its path, or for a remote store its URL in canonical form (`s3://bucket/key`, `gs://bucket/key`, `az://container/key (account <name>)`, or the HTTP(S) URL). Never contains credentials: URLs carrying them are rejected. |
| `level` | int | Resolved multiscale level the run operated on (the coarsest level if the request used the default). |
| `config.backend` | string | Always `"sam2"`; recorded for provenance (SAM2 is the only segmentation backend). |
| `config.level` | int | Requested level (`-1` means "coarsest"); `level` above is the resolved value. |
| `config.axes` | list[string] | Sweep axes; the first is the prompted axis, the rest are seeded from it (FR-022). |
| `config.direction` | string | `forward` or `forward_reverse` (FR-006). |
| `config.combine_rule` | string | Consensus rule across sweeps: `majority`, `union`, or `intersection` (FR-007). |
| `config.postprocess.source` | string | Where the steps came from: `cli` (`--postprocess`), `file` (`--postprocess-file`), `prompt_file` (saved with the prompts), `api`, `none` (`--postprocess none`), or `default` (nothing given and nothing saved: no steps). |
| `config.postprocess.steps` | list | The steps applied, in order: `op` (`fill`, `close`, `open`, `dilate`, `erode`, `margin`, `largest`, `invert`), `radius` as given (`"3"`, `"200um"`, or `null`) and `radius_voxels`, the radius in run-level voxels along each axis (`null` for steps without one). |
| `config.model_dir` | string | Resolved weights directory (explicit > `OME_ZARR_MASKER_MODEL_DIR` > `./ome_zarr_masker_models`). |
| `config.allow_download` | bool | Whether missing weights may be auto-downloaded. |
| `prompts.level` | int | Pyramid level the prompt coordinates were authored at (they were converted to `level` for the run). |
| `prompts.objects` | list | One entry per prompt: `obj_id`, `frame_index`, `points` (`xy` in `(x, y)`, `label` 1=positive/0=negative), and `box` (`[x0, y0, x1, y1]` or `null`), in authoring-level coordinates. |
| `output_layout` | list | One entry per output level: `level`, `shape`, `chunks`, `shards`, `compressor` (`blosc` zstd/3/bitshuffle) and `source` (`input` if copied from a sharded input level, else `default`). Contains no worker count, so it doesn't vary with `--workers`. |

## Example

Produced by:

```bash
ome-zarr-masker mask input.ome.zarr output.ome.zarr \
  --prompts prompts.json --level 0 --axes z,y --combine majority --postprocess close:3,fill
```

```json
{
  "run_id": "20261016T120000Z-1a2b3c4d5e6f",
  "input": "/data/input.ome.zarr",
  "level": 0,
  "config": {
    "backend": "sam2",
    "level": 0,
    "axes": ["z", "y"],
    "direction": "forward",
    "combine_rule": "majority",
    "postprocess": {
      "source": "cli",
      "steps": [
        {"op": "close", "radius": "3", "radius_voxels": [3.0, 3.0, 3.0]},
        {"op": "fill", "radius": null, "radius_voxels": null}
      ]
    },
    "model_dir": "/data/ome_zarr_masker_models",
    "allow_download": true
  },
  "prompts": {
    "level": 0,
    "objects": [
      {
        "obj_id": 0,
        "frame_index": 4,
        "points": [{"xy": [8.0, 8.0], "label": 1}],
        "box": [4.0, 4.0, 12.0, 12.0]
      }
    ]
  },
  "output_layout": [
    {"level": 0, "shape": [8, 16, 16], "chunks": [64, 64, 64], "shards": [64, 64, 64],
     "compressor": {"name": "blosc", "cname": "zstd", "clevel": 3, "shuffle": "bitshuffle"},
     "source": "default"},
    {"level": 1, "shape": [4, 8, 8], "chunks": [64, 64, 64], "shards": [64, 64, 64],
     "compressor": {"name": "blosc", "cname": "zstd", "clevel": 3, "shuffle": "bitshuffle"},
     "source": "default"}
  ]
}
```

## Reproducing a run

The record is sufficient to reconstruct the command: read `level`, `config.axes`,
`config.direction`, `config.combine_rule`, and `config.postprocess` for the flags (join the steps'
`op` and `radius` as `op:radius` into `--postprocess`), and translate
`prompts` back into a prompt file (`{"level": prompts.level, "objects": [...]}`; `points` and `box`
use the same SAM2 convention as the input prompt file). Given the same input store and weights, the run is deterministic.

The output's multiscale metadata keeps the input's axis units (e.g. `micrometer`), so physical
sizes mean the same in the mask as in the image.
