"""T015: CLI prompts are recorded with coordinates, labels, optional box, frame, and source."""

from __future__ import annotations

import json

import pytest

from ome_zarr_masker.cli import main
from ome_zarr_masker.io.reader import OmeZarrReader

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


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_cli_run_record_and_log_show_authoring_level(single_blob_zarr, tmp_path):
    """US2 Acceptance Scenario 1 / C-PF-7: the saved run_record.json and input log surface the
    prompt file's own authoring level, not the (possibly different) --level the run used.
    """
    store, _center, _frame = single_blob_zarr
    coarsest = OmeZarrReader(store).n_levels - 1
    prompts = tmp_path / "p.json"
    prompts.write_text(
        json.dumps(
            {
                "level": coarsest,
                "objects": [{"obj_id": 0, "points": [{"frame": 2, "xy": [4, 4], "label": 1}]}],
            }
        )
    )
    logdir = tmp_path / "logs"
    out = tmp_path / "out.ome.zarr"
    code = main(
        [
            "mask",
            str(store),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            str(coarsest),
            "--log-dir",
            str(logdir),
        ]
    )
    assert code == 0
    text = next(logdir.glob("*.log")).read_text()
    assert f"prompt_level: {coarsest}" in text
    record = json.loads((out / "run_record.json").read_text())
    assert record["prompts"]["level"] == coarsest
