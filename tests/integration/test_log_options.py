"""T020: --log-dir and --log-level override the defaults (C-LOG-CLI-6, FR-007)."""

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
def test_log_dir_and_level_are_honored(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr
    prompts = tmp_path / "p.json"
    _write_prompts(prompts, frame, cx, cy)
    custom = tmp_path / "custom_logs"
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
            str(custom),
            "--log-level",
            "DEBUG",
        ]
    )
    assert code == 0
    logs = list(custom.glob("*.log"))
    assert len(logs) == 1
    assert "log_level: DEBUG" in logs[0].read_text()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_default_log_dir_falls_back_to_env(single_blob_zarr, tmp_path, monkeypatch):
    store, (cx, cy), frame = single_blob_zarr
    prompts = tmp_path / "p.json"
    _write_prompts(prompts, frame, cx, cy)
    envdir = tmp_path / "env_logs"
    monkeypatch.setenv("OME_ZARR_MASKER_LOG_DIR", str(envdir))
    code = main(
        [
            "mask",
            str(store),
            str(tmp_path / "out.ome.zarr"),
            "--prompts",
            str(prompts),
            "--level",
            "0",
        ]
    )
    assert code == 0
    assert len(list(envdir.glob("*.log"))) == 1
