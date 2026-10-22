"""T010: distinct, non-colliding log files; log run id == output run-record run id.

Covers C-LOG-CLI-3 (no collision) and C-LOG-CLI-7 / FR-005 (run id correlation).
"""

from __future__ import annotations

import json

import pytest

from ome_zarr_masker.cli import main

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()


def _write_prompts(path, frame, cx, cy):
    path.write_text(
        json.dumps(
            {
                "level": 0,
                "objects": [
                    {"obj_id": 0, "points": [{"frame": frame, "xy": [cx, cy], "label": 1}]}
                ],
            }
        )
    )


def _run(store, out, prompts, logdir):
    return main(
        [
            "mask",
            str(store),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "0",
            "--log-dir",
            str(logdir),
        ]
    )


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_distinct_logs_and_runid_matches_record(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr
    prompts = tmp_path / "p.json"
    _write_prompts(prompts, frame, cx, cy)
    logdir = tmp_path / "logs"
    out1, out2 = tmp_path / "o1.ome.zarr", tmp_path / "o2.ome.zarr"

    assert _run(store, out1, prompts, logdir) == 0
    assert _run(store, out2, prompts, logdir) == 0

    logs = list(logdir.glob("*.log"))
    assert len(logs) == 2  # distinct files, no overwrite (C-LOG-CLI-3)

    rec1 = json.loads((out1 / "run_record.json").read_text())["run_id"]
    rec2 = json.loads((out2 / "run_record.json").read_text())["run_id"]
    assert rec1 != rec2

    # the log filename is <run_id>.log and its header run id matches the output run-record (FR-005)
    log_ids = {p.stem for p in logs}
    assert {rec1, rec2} == log_ids
    for p in logs:
        assert f"run_id: {p.stem}" in p.read_text()
