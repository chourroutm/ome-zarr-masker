"""T015: CLI prompts are recorded with coordinates, labels, optional box, frame, and source."""

from __future__ import annotations

import json

import pytest

from organ_masker_lite.cli import main

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_cli_point_prompts_recorded(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr
    prompts = tmp_path / "p.json"
    prompts.write_text(
        json.dumps(
            {
                "level": 0,
                "objects": [
                    {"obj_id": 0, "points": [{"frame": frame, "xy": [cx, cy], "label": 1}]}
                ],
            }
        )
    )
    logdir = tmp_path / "logs"
    code = main(
        [
            "mask",
            str(store),
            str(tmp_path / "out.ome.zarr"),
            "--prompts",
            str(prompts),
            "--level",
            "0",
            "--log-dir",
            str(logdir),
        ]
    )
    assert code == 0
    text = next(logdir.glob("*.log")).read_text()
    assert f"prompt_source: {prompts}" in text
    assert "prompt_count: 1" in text
    assert f"frame_index={frame}" in text
    assert f"point xy=[{float(cx)}, {float(cy)}] label=1" in text


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_cli_box_prompt_recorded(single_blob_zarr, tmp_path):
    store, _center, frame = single_blob_zarr
    prompts = tmp_path / "p.json"
    prompts.write_text(
        json.dumps(
            {
                "level": 0,
                "objects": [{"obj_id": 0, "box": {"frame": frame, "xyxy": [4, 4, 12, 12]}}],
            }
        )
    )
    logdir = tmp_path / "logs"
    code = main(
        [
            "mask",
            str(store),
            str(tmp_path / "out.ome.zarr"),
            "--prompts",
            str(prompts),
            "--level",
            "0",
            "--log-dir",
            str(logdir),
        ]
    )
    assert code == 0
    text = next(logdir.glob("*.log")).read_text()
    assert "box xyxy=[4.0, 4.0, 12.0, 12.0]" in text
