"""Round trips against real cloud storage (feature 010, T028; quickstart step 6).

Opt-in: each provider runs only when its ``OME_ZARR_MASKER_TEST_{S3,GCS,AZURE}_URL`` points to a
writable test prefix (with that provider's ambient credentials configured), e.g.
``OME_ZARR_MASKER_TEST_S3_URL=s3://my-test-bucket/ozm uv run pytest -m remote_live``.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from ome_zarr_masker.io.location import StoreLocation
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.io.writer import write_mask

from ..conftest import live_url, write_ome_zarr

pytestmark = pytest.mark.remote_live


@pytest.mark.parametrize("provider", ["S3", "GCS", "AZURE"])
def test_live_round_trip(provider, tmp_path):
    base = live_url(provider)
    if base is None:
        pytest.skip(f"OME_ZARR_MASKER_TEST_{provider}_URL is not set")

    vol = np.zeros((16, 32, 32), dtype=np.uint8)
    vol[2:14, 4:28, 4:28] = 200
    reader = OmeZarrReader(write_ome_zarr(tmp_path / "in.ome.zarr", vol, n_levels=3))
    mask = vol > 100
    local = write_mask(tmp_path / "local.ome.zarr", mask, 0, reader, {"tool": "live"})

    url = f"{base.rstrip('/')}/ozm-live-{uuid.uuid4().hex}.ome.zarr"
    location = StoreLocation.parse(url)
    try:
        assert write_mask(url, mask, 0, reader, {"tool": "live"}) == url
        remote, here = OmeZarrReader(url), OmeZarrReader(local)
        assert remote.n_levels == here.n_levels
        for i in range(here.n_levels):
            np.testing.assert_array_equal(remote.read_level(i), here.read_level(i))
    finally:
        from zarr.core.sync import sync

        sync(location.open_store(read_only=False).delete_dir(""))
