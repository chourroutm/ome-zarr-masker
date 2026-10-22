"""Unit tests for the intermediate-size preflight check (T015, FR-016)."""

from __future__ import annotations

import pytest

from ome_zarr_masker.engine.pipeline import (
    PipelineError,
    estimate_intermediate_bytes,
    preflight_disk,
)


def test_estimate_scales_with_voxels():
    small = estimate_intermediate_bytes((4, 8, 8))
    big = estimate_intermediate_bytes((8, 16, 16))
    assert big > small
    assert small == 256 * 5  # 256 voxels * (3 frame bytes + 2 vote bytes)


def test_preflight_passes_for_tiny_requirement(tmp_path):
    preflight_disk(1, tmp_path)  # no raise


def test_preflight_fails_when_requirement_exceeds_free(tmp_path):
    with pytest.raises(PipelineError):
        preflight_disk(10**18, tmp_path)
