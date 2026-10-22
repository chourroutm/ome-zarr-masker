"""T021: an unwritable --log-dir leaves the run successful with a single stderr warning.

Covers C-LOG-CLI-5 / FR-009 (best-effort logging never breaks the masking run).
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


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_unwritable_log_dir_does_not_break_run(single_blob_zarr, tmp_path, capsys):
    store, (cx, cy), frame = single_blob_zarr
    prompts = tmp_path / "p.json"
    _write_prompts(prompts, frame, cx, cy)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
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
            str(blocker / "sub"),  # cannot mkdir under a file
        ]
    )
    captured = capsys.readouterr()
    assert code == 0  # masking still succeeds
    assert out.exists()
    assert captured.err.count("input logging disabled") == 1  # exactly one warning
    assert "input logging disabled" not in captured.out  # never on stdout
