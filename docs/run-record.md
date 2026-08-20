# Run record (reproducibility)

Every mask written by organ-masker-lite embeds a `run_record.json` at the root of the output
OME-Zarr v0.5 store. It captures the full, reproducible parameterization of the run -- the input,
the level, the configuration, and the prompts -- so a result can be audited and re-created
(FR-014). The CLI, the Python API, and the interactive session all write the same record, because
they share one engine.

## Location

```
output.ome.zarr/
├── zarr.json            # OME-Zarr v0.5 multiscale metadata
├── 0/ 1/ ...            # mask pyramid levels (binary uint8, same level count as the input)
└── run_record.json      # this record
```

## Fields

| Field | Type | Meaning |
|-------|------|---------|
| `input` | string | Path to the input OME-Zarr v0.5 store. |
| `level` | int | Resolved multiscale level the run operated on (the coarsest level if the request used the default). |
| `config.backend` | string | Always `"sam2"`; recorded for provenance (SAM2 is the only segmentation backend). |
| `config.level` | int | Requested level (`-1` means "coarsest"); `level` above is the resolved value. |
| `config.axes` | list[string] | Sweep axes; the first is the prompted axis, the rest are seeded from it (FR-022). |
| `config.direction` | string | `forward` or `forward_reverse` (FR-006). |
| `config.combine_rule` | string | Consensus rule across sweeps: `majority`, `union`, or `intersection` (FR-007). |
| `config.postprocess.fill_holes` | bool | Whether interior holes were filled (default `true`). |
| `config.postprocess.dilation_radius` | int | Dilation iterations applied (default `0`). |
| `config.postprocess.erosion_radius` | int | Erosion iterations applied (default `0`). |
| `config.model_dir` | string | Resolved weights directory (explicit > `ORGAN_MASKER_MODEL_DIR` > `./organ_masker_models`). |
| `config.allow_download` | bool | Whether missing weights may be auto-downloaded. |
| `prompts` | list | One entry per prompt: `obj_id`, `frame_index`, `points` (`xy` in `(x, y)`, `label` 1=positive/0=negative), and `box` (`[x0, y0, x1, y1]` or `null`). |

## Example

Produced by:

```bash
organ-masker-lite mask input.ome.zarr output.ome.zarr \
  --prompts prompts.json --level 0 --axes z,y --combine majority
```

```json
{
  "input": "/data/input.ome.zarr",
  "level": 0,
  "config": {
    "backend": "sam2",
    "level": 0,
    "axes": ["z", "y"],
    "direction": "forward",
    "combine_rule": "majority",
    "postprocess": {
      "fill_holes": true,
      "dilation_radius": 0,
      "erosion_radius": 0
    },
    "model_dir": "/data/organ_masker_models",
    "allow_download": true
  },
  "prompts": [
    {
      "obj_id": 0,
      "frame_index": 4,
      "points": [{"xy": [8.0, 8.0], "label": 1}],
      "box": [4.0, 4.0, 12.0, 12.0]
    }
  ]
}
```

## Reproducing a run

The record is sufficient to reconstruct the command: read `level`, `config.axes`,
`config.direction`, `config.combine_rule`, and `config.postprocess` for the flags, and translate
each `prompts` entry back into a prompt file (`points` and `box` use the same SAM2 convention as the
input prompt file). Given the same input store and weights, the run is deterministic.
