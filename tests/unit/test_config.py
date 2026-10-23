"""Unit tests for RunConfig and model-directory resolution (T007; partial T014)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ome_zarr_masker.config import MODEL_DIR_ENV, RunConfig
from ome_zarr_masker.postprocess.steps import parse_steps


def test_default_model_dir_is_cwd_subdir(tmp_path, monkeypatch):
    monkeypatch.delenv(MODEL_DIR_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = RunConfig()
    assert cfg.resolved_model_dir() == tmp_path / "ome_zarr_masker_models"


def test_env_overrides_default(tmp_path, monkeypatch):
    monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path / "weights"))
    cfg = RunConfig()
    assert cfg.resolved_model_dir() == tmp_path / "weights"


def test_explicit_model_dir_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path / "env"))
    cfg = RunConfig(model_dir=Path(tmp_path / "explicit"))
    assert cfg.resolved_model_dir() == tmp_path / "explicit"


def test_to_record_round_trips_key_fields():
    cfg = RunConfig(level=2, axes=["z", "y"], combine_rule="majority")
    rec = cfg.to_record()
    assert rec["backend"] == "sam2"
    assert rec["level"] == 2
    assert rec["axes"] == ["z", "y"]
    assert rec["allow_download"] is True
    assert "model_dir" in rec


def test_postprocess_defaults_to_the_default_keyword():
    """Feature 011: no post-processing option means `default` (inherit saved steps, else none)."""
    cfg = RunConfig()
    assert cfg.postprocess.steps is None and cfg.postprocess.source == "default"
    assert cfg.to_record()["postprocess"] == {"source": "default", "steps": []}


def test_to_record_lists_steps_in_order():
    cfg = RunConfig(postprocess=parse_steps("close:3,fill,invert"))
    rec = cfg.to_record()["postprocess"]
    assert rec["source"] == "cli"
    assert [s["op"] for s in rec["steps"]] == ["close", "fill", "invert"]
    assert rec["steps"][0] == {"op": "close", "radius": "3", "radius_voxels": None}


def test_frame_range_defaults_to_none():
    assert RunConfig().frame_range is None


def test_frame_range_rejects_start_after_end():
    with pytest.raises(ValueError):
        RunConfig(frame_range=(5, 2))


def test_frame_range_rejects_negative_bounds():
    with pytest.raises(ValueError):
        RunConfig(frame_range=(-1, 2))
