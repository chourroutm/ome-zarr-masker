"""T011: with logging active, stdout carries no log lines (C-LOG-CLI-4, FR-008, SC-005)."""

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


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_stdout_is_only_the_output_path(single_blob_zarr, tmp_path, capsys):
    store, (cx, cy), frame = single_blob_zarr
    prompts = tmp_path / "p.json"
    _write_prompts(prompts, frame, cx, cy)
    out = tmp_path / "out.ome.zarr"
    code = main(
        [
            "mask",
            str(store),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "0",
            "--log-dir",
            str(tmp_path / "logs"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    # The only stdout content is the machine-readable output path; no log content leaks.
    assert captured.out.strip() == str(out)
    assert "run_id" not in captured.out
    assert "effective_config" not in captured.out
