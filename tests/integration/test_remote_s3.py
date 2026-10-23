"""S3 inputs and outputs against an in-process moto server (feature 010 US1/US3, T011/T021).

``moto_s3`` starts ``ThreadedMotoServer`` and points ``AWS_ENDPOINT_URL`` at it, so the real s3fs
code path runs offline. Segmentation uses ``StubBackend``: these tests check I/O equivalence.
"""

from __future__ import annotations

import json

import boto3
import numpy as np
import pytest

from ome_zarr_masker.cli import main
from ome_zarr_masker.config import RunConfig
from ome_zarr_masker.engine.pipeline import run_masking
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.prompts.model import Prompt, PromptSet

from ..conftest import StubBackend, upload_dir_to_s3, write_ome_zarr


def _blob_volume() -> np.ndarray:
    vol = np.zeros((8, 16, 16), dtype=np.uint8)
    vol[2:6, 4:12, 4:12] = 200
    return vol


def _prompts() -> PromptSet:
    return PromptSet([Prompt(frame_index=4, point_coords=[[8.0, 8.0]], point_labels=[1])])


def _levels(path) -> list[np.ndarray]:
    reader = OmeZarrReader(path)
    return [reader.read_level(i) for i in range(reader.n_levels)]


@pytest.fixture
def s3_input(moto_s3, tmp_path):
    """The blob fixture uploaded to ``s3://in-bkt/vol.ome.zarr``; returns ``(local, url)``."""
    local = write_ome_zarr(tmp_path / "in.ome.zarr", _blob_volume())
    boto3.client("s3").create_bucket(Bucket="in-bkt")
    upload_dir_to_s3(local, "in-bkt", "vol.ome.zarr")
    return local, "s3://in-bkt/vol.ome.zarr"


# -- read (US1) -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "form", ["s3://in-bkt/vol.ome.zarr", "https://in-bkt.s3.amazonaws.com/vol.ome.zarr"]
)
def test_s3_input_matches_local_input(s3_input, tmp_path, form):
    local, _ = s3_input
    cfg = RunConfig(axes=["z"], level=0)
    out_local = run_masking(local, tmp_path / "a.ome.zarr", _prompts(), cfg, backend=StubBackend())
    out_s3 = run_masking(form, tmp_path / "b.ome.zarr", _prompts(), cfg, backend=StubBackend())
    for a, b in zip(_levels(out_local), _levels(out_s3), strict=True):
        np.testing.assert_array_equal(a, b)
    rec = json.loads((out_s3 / "run_record.json").read_text())
    assert rec["input"] == "s3://in-bkt/vol.ome.zarr"


def test_public_bucket_read_without_credentials(s3_input, monkeypatch, tmp_path):
    """C-LOC-8 / US1 scenario 2: no credentials configured -> anonymous access still works."""
    local, _ = s3_input
    boto3.client("s3").create_bucket(Bucket="pub-bkt", ACL="public-read")
    upload_dir_to_s3(local, "pub-bkt", "vol.ome.zarr", public=True)
    url = "s3://pub-bkt/vol.ome.zarr"
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    from ome_zarr_masker.io import location as loc_mod

    assert not loc_mod._aws_credentials_available()
    reader = OmeZarrReader(url)
    np.testing.assert_array_equal(reader.read_level(0), OmeZarrReader(local).read_level(0))


# -- write (US3, T021) ------------------------------------------------------------------------


class _CountingStub(StubBackend):
    calls = 0

    def segment_video(self, frames, prompts):
        type(self).calls += 1
        return super().segment_video(frames, prompts)


@pytest.fixture
def stub_sam2(monkeypatch):
    """SAM2 replaced by a stub that counts its calls (to prove failures come before any work)."""
    from ome_zarr_masker.engine import pipeline

    _CountingStub.calls = 0
    monkeypatch.setattr(pipeline, "Sam2Backend", lambda config=None: _CountingStub())
    return _CountingStub


def _prompt_file(tmp_path):
    from pathlib import Path

    p = Path(tmp_path) / "prompts.json"
    p.write_text(
        json.dumps(
            {
                "level": 0,
                "objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}],
            }
        )
    )
    return p


def _files(root) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def assert_same_store(a, b) -> None:
    """Same files, byte for byte, apart from ``run_id`` in the run record (C-R-CLI-3)."""
    fa, fb = _files(a), _files(b)
    assert fa.keys() == fb.keys()
    for name in fa:
        if name == "run_record.json":
            ra, rb = json.loads(fa[name]), json.loads(fb[name])
            ra.pop("run_id", None)
            rb.pop("run_id", None)
            assert ra == rb
        else:
            assert fa[name] == fb[name], name


@pytest.fixture
def out_bucket(moto_s3):
    boto3.client("s3").create_bucket(Bucket="out-bkt")
    return "out-bkt"


def test_s3_output_equals_local_output(s3_input, out_bucket, stub_sam2, tmp_path, capsys):
    from ..conftest import assert_ome_zarr_models_valid, download_s3_dir

    _, url = s3_input
    prompts = _prompt_file(tmp_path)
    local_out = tmp_path / "local.ome.zarr"
    remote_out = "s3://out-bkt/mask.ome.zarr"
    for out in (str(local_out), remote_out):
        assert main(["mask", url, out, "--prompts", str(prompts), "--level", "0"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == remote_out

    fetched = download_s3_dir(out_bucket, "mask.ome.zarr", tmp_path / "fetched.ome.zarr")
    assert_ome_zarr_models_valid(fetched)
    assert_same_store(local_out, fetched)
    assert OmeZarrReader(remote_out).read_level(0).any()


def test_s3_output_overwrite_rules(s3_input, out_bucket, stub_sam2, tmp_path, capsys):
    """C-R-CLI-4: an existing remote output fails before segmentation; --overwrite replaces it."""
    _, url = s3_input
    prompts = _prompt_file(tmp_path)
    out = "s3://out-bkt/mask.ome.zarr"
    args = ["mask", url, out, "--prompts", str(prompts), "--level", "0"]
    assert main(args) == 0
    capsys.readouterr()

    stub_sam2.calls = 0
    assert main(args) == 1
    err = capsys.readouterr().err
    assert "already exists" in err and out in err
    assert stub_sam2.calls == 0

    assert main([*args, "--overwrite"]) == 0
    assert stub_sam2.calls > 0


def test_same_store_for_input_and_output_rejected(s3_input, stub_sam2, tmp_path, capsys):
    """C-R-CLI-6: input and output naming one store (in different forms) fail before any work."""
    prompts = _prompt_file(tmp_path)
    out = "https://in-bkt.s3.amazonaws.com/vol.ome.zarr/"
    code = main(["mask", "s3://in-bkt/vol.ome.zarr", out, "--prompts", str(prompts), "--overwrite"])
    captured = capsys.readouterr()
    assert code == 1 and stub_sam2.calls == 0
    assert "same store" in captured.err
    assert OmeZarrReader("s3://in-bkt/vol.ome.zarr").n_levels == 2  # input untouched


def test_generic_https_output_rejected_before_work(s3_input, stub_sam2, tmp_path, capsys):
    """C-LOC-5 / US3 scenario 4."""
    _, url = s3_input
    prompts = _prompt_file(tmp_path)
    code = main(["mask", url, "https://example.org/m.ome.zarr", "--prompts", str(prompts)])
    err = capsys.readouterr().err
    assert code == 1 and stub_sam2.calls == 0
    assert "read-only" in err and "s3://" in err and "gs://" in err and "az://" in err
