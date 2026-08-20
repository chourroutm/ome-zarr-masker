"""US3: choosing the resolution (binning) level (T043, FR-003).

A valid level runs and the output is a pyramid matching the input's level grids; a missing level
reports the available levels and aborts with no partial output; the coarsest level is the default
when unspecified.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from organ_masker_lite.cli import main
from organ_masker_lite.io.reader import OmeZarrReader

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()
requires_sam2 = pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")


def _prompts(path: Path, frame: int, xy: list[int]) -> Path:
    path.write_text(
        json.dumps({"objects": [{"obj_id": 0, "points": [{"frame": frame, "xy": xy, "label": 1}]}]})
    )
    return path


def _run(store, out, prompts, *level):
    argv = ["mask", str(store), str(out), "--prompts", str(prompts)]
    if level:
        argv += ["--level", str(level[0])]
    return main(argv)


@pytest.mark.real_backend
@requires_sam2
def test_valid_level_output_grid_matches_input_levels(single_blob_zarr, tmp_path):
    store, _center, _frame = single_blob_zarr  # level 0 shape (8, 16, 16), blob center (8, 8) @ z=4
    out = tmp_path / "lvl0.ome.zarr"
    assert _run(store, out, _prompts(tmp_path / "p0.json", 4, [8, 8]), 0) == 0

    rin = OmeZarrReader(store)
    rout = OmeZarrReader(out)
    assert rout.n_levels == rin.n_levels
    for i in range(rin.n_levels):
        assert rout.level_shape(i) == rin.level_shape(i)
    assert json.loads((out / "run_record.json").read_text())["level"] == 0
    assert rout.read_level(0).any()


@pytest.mark.real_backend
@requires_sam2
def test_default_level_is_coarsest_when_unspecified(single_blob_zarr, tmp_path):
    store, _center, _frame = single_blob_zarr
    # coarsest level (index 1) has shape (4, 8, 8); the blob there is centred at (4, 4) on frame 2
    out = tmp_path / "default.ome.zarr"
    assert _run(store, out, _prompts(tmp_path / "pc.json", 2, [4, 4])) == 0

    coarsest = OmeZarrReader(store).n_levels - 1
    assert json.loads((out / "run_record.json").read_text())["level"] == coarsest


def test_missing_level_reports_available_and_leaves_no_output(single_blob_zarr, tmp_path, capsys):
    store, _center, _frame = single_blob_zarr
    out = tmp_path / "missing.ome.zarr"
    code = _run(store, out, _prompts(tmp_path / "p.json", 4, [8, 8]), 99)

    assert code == 1
    assert not out.exists()
    assert "available levels" in capsys.readouterr().err
