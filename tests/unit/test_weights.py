"""Unit tests for weight resolution and the injectable downloader (T014).

Exercises ``RunConfig.resolve_weight`` -- the seam every backend uses to find or fetch its
weights -- without touching the network: a fake fetcher stands in for the real download.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ome_zarr_masker.config import RunConfig, default_weight_downloader

_URL = "https://example.invalid/weights/model.pt"


def test_existing_weight_used_as_is_without_download(tmp_path):
    """A weight already on disk is returned as-is and the downloader is never invoked."""
    ckpt = tmp_path / "model.pt"
    ckpt.write_bytes(b"pretend weights")
    calls: list[tuple[str, Path]] = []

    cfg = RunConfig(model_dir=tmp_path)
    resolved = cfg.resolve_weight(
        "model.pt", _URL, downloader=lambda url, dest: calls.append((url, dest))
    )

    assert resolved == ckpt
    assert calls == []  # no download attempted


def test_auto_download_invoked_on_first_use(tmp_path):
    """A missing weight triggers the injected fetcher exactly once with (url, dest)."""
    calls: list[tuple[str, Path]] = []

    def fake_fetch(url: str, dest: Path) -> None:
        calls.append((url, dest))
        dest.write_bytes(b"downloaded weights")

    cfg = RunConfig(model_dir=tmp_path)
    resolved = cfg.resolve_weight("model.pt", _URL, downloader=fake_fetch)

    assert resolved == tmp_path / "model.pt"
    assert calls == [(_URL, tmp_path / "model.pt")]
    assert resolved.read_bytes() == b"downloaded weights"


def test_download_creates_missing_model_dir(tmp_path):
    """The model directory is created on demand before the download runs."""
    model_dir = tmp_path / "nested" / "weights"
    cfg = RunConfig(model_dir=model_dir)
    cfg.resolve_weight("model.pt", _URL, downloader=lambda url, dest: dest.write_bytes(b"w"))

    assert (model_dir / "model.pt").exists()


def test_no_download_with_missing_weight_raises_clear_error(tmp_path):
    """``allow_download=False`` with absent weights raises a clear, named error (no network)."""
    cfg = RunConfig(model_dir=tmp_path, allow_download=False)

    def forbidden(url: str, dest: Path) -> None:  # pragma: no cover - must not run
        raise AssertionError("download must not be attempted when allow_download is False")

    with pytest.raises(FileNotFoundError) as exc:
        cfg.resolve_weight("model.pt", _URL, description="SAM2 checkpoint", downloader=forbidden)

    message = str(exc.value)
    assert "SAM2 checkpoint" in message
    assert "--no-download" in message
    assert str(tmp_path / "model.pt") in message


def test_absolute_filename_is_used_verbatim(tmp_path):
    """An absolute ``filename`` bypasses the model directory entirely."""
    target = tmp_path / "elsewhere" / "abs.pt"
    cfg = RunConfig(model_dir=tmp_path / "ignored")
    cfg.resolve_weight(str(target), _URL, downloader=lambda url, dest: dest.write_bytes(b"w"))

    assert target.exists()


def test_default_downloader_writes_atomically(tmp_path, monkeypatch):
    """The default downloader stages a ``.part`` file then renames it into place (no network)."""
    dest = tmp_path / "model.pt"
    seen: dict[str, Path] = {}

    def fake_urlretrieve(url: str, filename):
        staged = Path(filename)
        seen["staged"] = staged
        staged.write_bytes(b"bytes")

    monkeypatch.setattr("urllib.request.urlretrieve", fake_urlretrieve)
    default_weight_downloader(_URL, dest)

    assert seen["staged"] == dest.with_suffix(".pt.part")  # staged to a temp sibling
    assert not seen["staged"].exists()  # renamed away
    assert dest.read_bytes() == b"bytes"
