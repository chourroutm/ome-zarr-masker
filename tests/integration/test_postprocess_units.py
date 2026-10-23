"""Physical post-processing radii end to end (feature 011 US2, T017: SC-002, C-PP-3).

SAM2 is replaced by ``StubBackend`` (foreground = bright voxels): these tests check how radii are
resolved and applied at different levels, not segmentation.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from ome_zarr_masker.cli import main
from ome_zarr_masker.config import RunConfig
from ome_zarr_masker.engine.pipeline import run_masking
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.postprocess.steps import parse_steps
from ome_zarr_masker.prompts.model import Prompt, PromptSet

from ..conftest import StubBackend, write_ome_zarr


def _volume() -> np.ndarray:
    vol = np.zeros((32, 64, 64), np.uint8)
    vol[8:24, 16:48, 16:48] = 200
    return vol


def _bounds(mask: np.ndarray) -> list[tuple[int, int]]:
    """First and last foreground index along each axis, through the volume centre."""
    centre = [n // 2 for n in mask.shape]
    out = []
    for axis in range(mask.ndim):
        line = list(centre)
        line[axis] = slice(None)
        idx = np.flatnonzero(mask[tuple(line)])
        out.append((int(idx[0]), int(idx[-1])))
    return out


def test_physical_margin_has_the_same_thickness_at_two_levels(tmp_path):
    """SC-002: margin:8um at level 0 (1 µm voxels) and level 1 (2 µm voxels)."""
    store = write_ome_zarr(tmp_path / "in.ome.zarr", _volume(), units=("micrometer",) * 3)
    prompts = PromptSet(
        [Prompt(frame_index=16, point_coords=[[32.0, 32.0]], point_labels=[1])], level=0
    )

    outs = {}
    for level in (0, 1):
        cfg = RunConfig(level=level, axes=["z"], postprocess=parse_steps("margin:8um"))
        out = tmp_path / f"l{level}.ome.zarr"
        run_masking(store, out, prompts, cfg, backend=StubBackend())
        outs[level] = OmeZarrReader(out).read_level(0).astype(bool)
        rec = json.loads((out / "run_record.json").read_text())["config"]["postprocess"]
        expected = 8.0 / (1.0 if level == 0 else 2.0)
        assert rec["steps"][0]["radius_voxels"] == pytest.approx([expected] * 3)

    raw = _volume() > 100
    b0, b1, braw = _bounds(outs[0]), _bounds(outs[1]), _bounds(raw)
    for (lo0, hi0), (lo1, hi1), (lor, hir) in zip(b0, b1, braw, strict=True):
        assert (lor - lo0, hi0 - hir) == (8, 8)  # level 0: exactly 8 µm on each side
        assert abs(lo1 - lo0) <= 2 and abs(hi1 - hi0) <= 2  # within one level-1 voxel (2 µm)


def test_physical_radius_without_units_fails_before_segmentation(tmp_path, monkeypatch, capsys):
    from ome_zarr_masker.engine import pipeline

    calls = []
    monkeypatch.setattr(pipeline, "Sam2Backend", lambda config=None: calls.append(1))
    store = write_ome_zarr(tmp_path / "in.ome.zarr", _volume())
    prompts = tmp_path / "p.json"
    prompts.write_text(
        json.dumps(
            {"level": 0, "objects": [{"points": [{"frame": 16, "xy": [32, 32], "label": 1}]}]}
        )
    )
    out = tmp_path / "out.ome.zarr"
    code = main(
        ["mask", str(store), str(out), "--prompts", str(prompts), "--postprocess", "margin:200um"]
    )
    err = capsys.readouterr().err
    assert code == 1 and calls == [] and not out.exists()
    assert "margin:200um" in err and "unit" in err
