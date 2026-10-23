"""Real-data check of ordered post-processing on a small DANDI 001278 volume (feature 011, T035).

Not part of the test suite (pytest only collects ``tests/``): it needs SAM2 (a GPU node) and
network access to DANDI. Run it with ``validation/run_dandi_001278.sh OUTDIR``.

The input is the smallest image of dandiset 001278,
``sourcedata/raw/sub-Hb1/micr/sub-Hb1_sample-lefthemi+ICblock+punch1+piece2_uCT.ome.zarr``
(asset 7fdc9b48-aca4-4505-bcb7-4a92330136a6), read remotely at level 2 (251 x 256 x 140 voxels of
35.94 um). A positive prompt is placed automatically on the middle z frame and saved in a prompt
file together with post-processing steps in physical units; ``mask`` then runs twice, once
inheriting those steps (no --postprocess) and once with ``--postprocess none``. The checks are
printed as JSON; the exit status is 1 if any check fails.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

from ome_zarr_masker.cli import main
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.io.validate import validate_ome_zarr
from ome_zarr_masker.postprocess.morphology import apply_steps
from ome_zarr_masker.postprocess.steps import parse_steps, resolve_steps

URL = "https://dandiarchive.s3.amazonaws.com/zarr/8507935b-39a0-4ce4-87da-58906eebdb74"
LEVEL = 2
STEPS = ["close:100um", "fill", "largest", "margin:72um"]


def otsu_threshold(values: np.ndarray) -> float:
    """Otsu's threshold over a 256-bin histogram (no extra dependency)."""
    hist, edges = np.histogram(values, bins=256)
    centres = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centres) / np.maximum(w0, 1)
    m1 = (np.sum(hist * centres) - np.cumsum(hist * centres)) / np.maximum(w1, 1)
    return float(centres[np.argmax(w0 * w1 * (m0 - m1) ** 2)])


def place_prompt(volume: np.ndarray) -> tuple[int, float, float]:
    """The most interior voxel of the largest bright region on the middle z frame."""
    frame = volume.shape[0] // 2
    plane = volume[frame].astype(np.float32)
    bright = plane > otsu_threshold(plane)
    labels, n = ndimage.label(bright)
    if n == 0:
        raise SystemExit("no bright region on the middle frame to prompt")
    largest = labels == 1 + int(np.argmax(np.bincount(labels.ravel())[1:]))
    y, x = np.unravel_index(int(np.argmax(ndimage.distance_transform_edt(largest))), plane.shape)
    return frame, float(x), float(y)


def dice(a: np.ndarray, b: np.ndarray) -> float:
    return float(2 * (a & b).sum() / max(1, a.sum() + b.sum()))


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    reader = OmeZarrReader(URL)
    volume = reader.read_level(LEVEL)
    frame, x, y = place_prompt(volume)
    prompts = out_dir / "prompts.json"
    obj = {"obj_id": 0, "points": [{"frame": frame, "xy": [x, y], "label": 1}]}
    prompts.write_text(json.dumps({"level": LEVEL, "objects": [obj], "postprocess": STEPS}))

    common = ["--prompts", str(prompts), "--level", str(LEVEL), "--axes", "z,y,x",
              "--direction", "forward_reverse", "--overwrite"]  # fmt: skip
    default_out, raw_out = out_dir / "default.ome.zarr", out_dir / "raw.ome.zarr"
    codes = {
        "default": main(["mask", URL, str(default_out), *common]),
        "raw": main(["mask", URL, str(raw_out), *common, "--postprocess", "none"]),
    }

    checks: dict[str, bool] = {"both runs exit 0": codes == {"default": 0, "raw": 0}}
    report: dict = {"input": URL, "level": LEVEL, "prompt": [frame, x, y], "exit_codes": codes}
    if not checks["both runs exit 0"]:
        return {**report, "checks": checks}

    for name, path in (("default", default_out), ("raw", raw_out)):
        try:
            validate_ome_zarr(path)
            checks[f"{name} output is valid OME-Zarr v0.5"] = True
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            checks[f"{name} output is valid OME-Zarr v0.5"] = False
            report[f"{name}_validation_error"] = str(exc)

    record = json.loads((default_out / "run_record.json").read_text())["config"]["postprocess"]
    scale = reader.level_transform(LEVEL)[0]
    expected_voxels = [[100 / s for s in scale], [72 / s for s in scale]]
    radii = [s["radius_voxels"] for s in record["steps"] if s["radius_voxels"] is not None]
    checks["steps inherited from the prompt file"] = record["source"] == "prompt_file"
    checks["recorded steps match the prompt file"] = [
        s["op"] + (f":{s['radius']}" if s["radius"] else "") for s in record["steps"]
    ] == STEPS
    checks["physical radii resolved per axis"] = all(
        np.allclose(got, want, rtol=1e-9) for got, want in zip(radii, expected_voxels, strict=True)
    )
    out_reader = OmeZarrReader(default_out)
    checks["output keeps micrometre axes"] = out_reader.axis_units == ["micrometer"] * 3

    raw = OmeZarrReader(raw_out).read_level(LEVEL).astype(bool)
    final = out_reader.read_level(LEVEL).astype(bool)
    resolved = resolve_steps(parse_steps(STEPS).steps, scale, reader.axis_units)
    checks["written mask == steps applied to the raw mask"] = bool(
        np.array_equal(final, apply_steps(raw, resolved))
    )
    _, n_components = ndimage.label(final, structure=np.ones((3, 3, 3)))
    checks["one connected component"] = n_components == 1
    checks["neither empty nor the whole volume"] = 0 < int(final.sum()) < final.size

    bright = volume > otsu_threshold(volume.astype(np.float32))
    report.update(
        {
            "voxels": {"raw": int(raw.sum()), "final": int(final.sum()), "total": final.size},
            "radius_voxels": radii,
            # informative: `largest` may drop raw fragments, and a margin may enclose cavities
            "raw voxels kept (informative)": round(
                float((raw & final).sum()) / max(1, raw.sum()), 4
            ),
            "3D holes in the result (informative)": int(
                (ndimage.binary_fill_holes(final) & ~final).sum()
            ),
            "dice_vs_otsu_threshold (informative)": round(dice(final, bright), 4),
        }
    )
    return {**report, "checks": checks}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} OUTPUT_DIR")
    result = run(Path(sys.argv[1]))
    print(json.dumps(result, indent=2))
    sys.exit(0 if all(result["checks"].values()) else 1)
