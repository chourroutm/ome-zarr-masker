"""Unit tests for RunConfig and model-directory resolution (T007; partial T014)."""

from __future__ import annotations

from pathlib import Path

from organ_masker_lite.config import MODEL_DIR_ENV, RunConfig


def test_default_model_dir_is_cwd_subdir(tmp_path, monkeypatch):
    monkeypatch.delenv(MODEL_DIR_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = RunConfig()
    assert cfg.resolved_model_dir() == tmp_path / "organ_masker_models"


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
