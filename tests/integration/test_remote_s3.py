"""S3 inputs and outputs against an in-process moto server (feature 010 US1/US3, T011/T021).

``moto_s3`` starts ``ThreadedMotoServer`` and points ``AWS_ENDPOINT_URL`` at it, so the real s3fs
code path runs offline. Segmentation uses ``StubBackend``: these tests check I/O equivalence.
"""

from __future__ import annotations

import json

import boto3
import numpy as np
import pytest

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
