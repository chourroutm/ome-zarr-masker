"""T009: a CLI run that fails before output still writes a log (C-LOG-CLI-2, FR-002)."""

from __future__ import annotations

import json

from organ_masker_lite.cli import main


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


def test_failed_cli_run_still_writes_log(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr
    prompts = tmp_path / "p.json"
    _write_prompts(prompts, frame, cx, cy)
    logdir = tmp_path / "logs"
    # An invalid level is rejected during config construction, before any output is produced.
    code = main(
        [
            "mask",
            str(store),
            str(tmp_path / "out.ome.zarr"),
            "--prompts",
            str(prompts),
            "--level",
            "-5",
            "--log-dir",
            str(logdir),
        ]
    )
    assert code == 1
    logs = list(logdir.glob("*.log"))
    assert len(logs) == 1
    text = logs[0].read_text()
    assert "command: organ-masker-lite mask" in text
    assert "outcome: failed" in text
