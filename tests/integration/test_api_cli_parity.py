"""API/CLI parity: identical inputs/prompts produce equivalent masks (T047, C-API-6, SC-005)."""

from __future__ import annotations

import json

import pytest

from ome_zarr_masker import OrganMaskPredictor
from ome_zarr_masker.cli import main
from ome_zarr_masker.io.reader import OmeZarrReader

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
            {
                "level": 0,
                "objects": [
                    {"obj_id": 0, "points": [{"frame": frame, "xy": [cx, cy], "label": 1}]}
                ],
            }
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
    predictor.add_prompts(frame_index=frame, point_coords=[[cx, cy]], point_labels=[1])
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


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_api_and_cli_agree_across_worker_counts(single_blob_zarr, tmp_path):
    """Feature 009 (C-W-API-1/2/4): worker count changes neither the output nor the run record."""
    from ome_zarr_masker.io.writer import WriterError

    store, (cx, cy), frame = single_blob_zarr
    prompts_file = tmp_path / "p.json"
    prompts_file.write_text(
        json.dumps(
            {
                "level": 0,
                "objects": [
                    {"obj_id": 0, "points": [{"frame": frame, "xy": [cx, cy], "label": 1}]}
                ],
            }
        )
    )
    cli_out = tmp_path / "cli.ome.zarr"
    argv = [
        "mask",
        str(store),
        str(cli_out),
        "--prompts",
        str(prompts_file),
        "--level",
        "0",
        "--workers",
        "3",
    ]
    assert main(argv) == 0

    predictor = OrganMaskPredictor().set_volume(store, level=0)
    predictor.add_prompts(frame_index=frame, point_coords=[[cx, cy]], point_labels=[1])
    result = predictor.predict(axes=["z"])
    api_out = result.save(tmp_path / "api.ome.zarr", workers=1)

    cli_reader, api_reader = OmeZarrReader(cli_out), OmeZarrReader(api_out)
    for i in range(cli_reader.n_levels):
        assert (cli_reader.read_level(i) == api_reader.read_level(i)).all()
    cli_record = json.loads((cli_out / "run_record.json").read_text())
    api_record = json.loads((api_out / "run_record.json").read_text())
    cli_record.pop("run_id")
    api_record.pop("run_id")
    assert cli_record == api_record

    bad = tmp_path / "bad.ome.zarr"
    with pytest.raises(WriterError):
        result.save(bad, workers=0)
    assert not bad.exists()
