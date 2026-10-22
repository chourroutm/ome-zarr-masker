"""Unit tests for in-process OME-Zarr v0.5 input validation (feature 003).

Validation runs in-process via the installed ``ome-zarr-models`` package, with no dependency on a
validator command being discoverable on ``PATH`` (T002, T003, T004, T008). The existing
valid/invalid/missing cases (T011 from feature 001) are preserved to guard against regressions.
"""

from __future__ import annotations

import builtins
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

from ome_zarr_masker.io.validate import ValidationError, validate_ome_zarr

from ..conftest import write_ome_zarr


def _valid_store(tmp_path):
    vol = np.zeros((8, 16, 16), np.uint8)
    vol[2:6, 4:12, 4:12] = 200
    return write_ome_zarr(tmp_path / "in.ome.zarr", vol)


def _junk_store(tmp_path):
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "hello.txt").write_text("not a zarr")
    return junk


def _v04_store(tmp_path):
    """A minimal OME-Zarr v0.4 store: Zarr format 2 (.zgroup/.zattrs), no zarr.json."""
    store = tmp_path / "v04.ome.zarr"
    store.mkdir()
    (store / ".zgroup").write_text('{"zarr_format": 2}')
    (store / ".zattrs").write_text(
        '{"multiscales": [{"version": "0.4", "axes": [], "datasets": []}]}'
    )
    return store


# --- Feature 001 behaviour preserved (C-VAL-3, C-VAL-4, C-VAL-6) ---------------------------------


def test_valid_store_passes(tmp_path):
    validate_ome_zarr(_valid_store(tmp_path))  # no raise


def test_missing_path_raises(tmp_path):
    with pytest.raises(ValidationError):
        validate_ome_zarr(tmp_path / "nope.ome.zarr")


def test_non_ome_store_raises(tmp_path):
    with pytest.raises(ValidationError):
        validate_ome_zarr(_junk_store(tmp_path))


def test_v04_store_raises_clear_version_mismatch_error(tmp_path):
    """A v0.4/Zarr-format-2 store must fail with a message naming the actual version and
    format, not the raw 'no group at path ...' error from zarr's v3-only group lookup."""
    with pytest.raises(ValidationError) as excinfo:
        validate_ome_zarr(_v04_store(tmp_path))
    message = str(excinfo.value)
    assert "v0.4" in message
    assert "Zarr format 2" in message
    assert "v0.5" in message


# --- US1: validate from a plain install, no validator command on PATH ----------------------------


def test_valid_store_passes_without_validator_on_path(tmp_path, monkeypatch):
    """C-VAL-1: a valid store validates even with no ome-zarr-models command discoverable."""
    store = _valid_store(tmp_path)
    # No ome-zarr-models command on PATH, and none next to the interpreter either.
    monkeypatch.setenv("PATH", str(tmp_path / "empty_bin"))
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    validate_ome_zarr(store)  # in-process: no raise


def test_validation_spawns_no_subprocess(tmp_path, monkeypatch):
    """C-VAL-2: neither a passing nor a failing validation spawns a child process."""

    def boom(*a, **k):
        raise AssertionError("validation must not spawn a subprocess")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)

    validate_ome_zarr(_valid_store(tmp_path))  # passes via in-process path
    with pytest.raises(ValidationError):
        validate_ome_zarr(_junk_store(tmp_path))  # rejected, still no subprocess


def test_missing_dependency_raises_actionable_error(tmp_path, monkeypatch):
    """C-VAL-5: if ome-zarr-models cannot be imported, the error names it and how to install it."""
    store = _valid_store(tmp_path)  # build the store before breaking the import

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ome_zarr_models" or name.startswith("ome_zarr_models."):
            raise ImportError("No module named 'ome_zarr_models'")
        return real_import(name, *args, **kwargs)

    loaded = [m for m in sys.modules if m == "ome_zarr_models" or m.startswith("ome_zarr_models.")]
    for mod in loaded:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ValidationError) as excinfo:
        validate_ome_zarr(store)
    message = str(excinfo.value)
    assert "ome-zarr-models" in message
    assert "install" in message.lower()


# --- US3: predictable validation regardless of any on-PATH command -------------------------------


def test_conflicting_validator_on_path_is_ignored(tmp_path, monkeypatch):
    """A broken/conflicting ome-zarr-models earlier on PATH must never affect the outcome."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "ome-zarr-models"
    fake.write_text("#!/bin/sh\necho BROKEN >&2\nexit 3\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")

    validate_ome_zarr(_valid_store(tmp_path))  # in-process: broken command ignored
    with pytest.raises(ValidationError):
        validate_ome_zarr(_junk_store(tmp_path))
