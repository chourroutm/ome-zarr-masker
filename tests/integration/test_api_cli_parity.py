"""API/CLI parity: identical inputs/prompts produce equivalent masks (T047, C-API-6, SC-005)."""

from __future__ import annotations

import json

import pytest

from organ_masker_lite import OrganMaskPredictor
from organ_masker_lite.cli import main
from organ_masker_lite.io.reader import OmeZarrReader

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_api_and_cli_produce_equivalent_masks(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr

    # CLI path
    prompts_file = tmp_path / "p.json"
    prompts_file.write_text(
        json.dumps(
            {"objects": [{"obj_id": 0, "points": [{"frame": frame, "xy": [cx, cy], "label": 1}]}]}
        )
    )
    cli_out = tmp_path / "cli.ome.zarr"
    code = main(
        [
            "mask",
            str(store),
            str(cli_out),
            "--prompts",
            str(prompts_file),
            "--level",
            "0",
        ]
    )
    assert code == 0

    # API path with the same input/prompts/level
    predictor = OrganMaskPredictor().set_volume(store, level=0)
    predictor.add_points_or_box(frame_index=frame, point_coords=[[cx, cy]], point_labels=[1])
    api_out = predictor.predict(axes=["z"]).save(tmp_path / "api.ome.zarr")

    cli_reader = OmeZarrReader(cli_out)
    api_reader = OmeZarrReader(api_out)
    assert cli_reader.n_levels == api_reader.n_levels
    for i in range(cli_reader.n_levels):
        assert (cli_reader.read_level(i) == api_reader.read_level(i)).all()

    # the embedded run records match too (same config + prompts); run_id is per-invocation
    # and intentionally differs, so it is excluded from the parity comparison (feature 002).
    cli_record = json.loads((cli_out / "run_record.json").read_text())
    api_record = json.loads((api_out / "run_record.json").read_text())
    assert cli_record.pop("run_id") != api_record.pop("run_id")
    assert cli_record == api_record
