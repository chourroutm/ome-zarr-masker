"""US3: choosing the resolution (binning) level (T043, FR-003).

A valid level runs and the output is a pyramid matching the input's level grids; a missing level
reports the available levels and aborts with no partial output; the coarsest level is the default
when unspecified.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from organ_masker_lite.cli import main
from organ_masker_lite.io.reader import OmeZarrReader

from ..conftest import sam2_available, write_ome_zarr

_HAVE_SAM2 = sam2_available()
requires_sam2 = pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")


def _prompts(path: Path, frame: int, xy: list[int], level: int = 0) -> Path:
    path.write_text(
        json.dumps(
            {
                "level": level,
                "objects": [{"obj_id": 0, "points": [{"frame": frame, "xy": xy, "label": 1}]}],
            }
        )
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
    assert _run(store, out, _prompts(tmp_path / "p0.json", 4, [8, 8], level=0), 0) == 0

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
    coarsest = OmeZarrReader(store).n_levels - 1
    assert _run(store, out, _prompts(tmp_path / "pc.json", 2, [4, 4], level=coarsest)) == 0

    assert json.loads((out / "run_record.json").read_text())["level"] == coarsest


def test_missing_level_reports_available_and_leaves_no_output(single_blob_zarr, tmp_path, capsys):
    store, _center, _frame = single_blob_zarr
    out = tmp_path / "missing.ome.zarr"
    code = _run(store, out, _prompts(tmp_path / "p.json", 4, [8, 8]), 99)

    assert code == 1
    assert not out.exists()
    assert "available levels" in capsys.readouterr().err


# -- feature 008-level-agnostic-prompts: cross-level reuse (US1) --------------------------------


@pytest.mark.real_backend
@requires_sam2
def test_prompt_authored_at_one_level_reused_at_another(single_blob_zarr, tmp_path):
    """US1 Acceptance Scenario 1 / SC-001: a prompt set authored at level 0 and run at the
    coarsest level locates the same anatomical feature as one authored directly at that level.
    """
    store, (cx, cy), frame = single_blob_zarr
    reader = OmeZarrReader(store)
    coarsest = reader.n_levels - 1
    level0_shape, coarse_shape = reader.level_shape(0), reader.level_shape(coarsest)

    # authored at level 0, converted to the coarsest level at run time
    converted_out = tmp_path / "converted.ome.zarr"
    converted_prompts = _prompts(tmp_path / "p_level0.json", frame, [cx, cy], level=0)
    assert _run(store, converted_out, converted_prompts, coarsest) == 0

    # authored directly at the coarsest level (today's pre-feature baseline behavior)
    x_ratio = coarse_shape[2] / level0_shape[2]
    y_ratio = coarse_shape[1] / level0_shape[1]
    z_ratio = coarse_shape[0] / level0_shape[0]
    native_xy = [round(cx * x_ratio), round(cy * y_ratio)]
    native_frame = round(frame * z_ratio)
    native_out = tmp_path / "native.ome.zarr"
    native_prompts = _prompts(tmp_path / "p_native.json", native_frame, native_xy, level=coarsest)
    assert _run(store, native_out, native_prompts, coarsest) == 0

    rconv, rnative = OmeZarrReader(converted_out), OmeZarrReader(native_out)
    assert (rconv.read_level(coarsest) == rnative.read_level(coarsest)).all()
    assert rconv.read_level(coarsest).any()


@pytest.mark.real_backend
@requires_sam2
def test_same_level_rerun_is_byte_identical(single_blob_zarr, tmp_path):
    """FR-006/SC-002: authoring level == run level must stay byte-identical to pre-feature
    behavior -- the conversion path must be a true no-op here, not a recomputed 1.0 ratio.
    """
    store, (cx, cy), frame = single_blob_zarr
    prompts = _prompts(tmp_path / "p.json", frame, [cx, cy], level=0)

    out_a, out_b = tmp_path / "a.ome.zarr", tmp_path / "b.ome.zarr"
    assert _run(store, out_a, prompts, 0) == 0
    assert _run(store, out_b, prompts, 0) == 0

    ra, rb = OmeZarrReader(out_a), OmeZarrReader(out_b)
    for i in range(ra.n_levels):
        assert (ra.read_level(i) == rb.read_level(i)).all()

    record_a = json.loads((out_a / "run_record.json").read_text())
    record_b = json.loads((out_b / "run_record.json").read_text())
    record_a.pop("run_id")
    record_b.pop("run_id")
    assert record_a == record_b


def test_out_of_bounds_after_conversion_still_raises(single_blob_zarr, tmp_path, monkeypatch):
    """Edge Cases / FR-005: if a level's metadata maps an in-bounds authored point outside the run
    level, the pipeline's existing bounds check rejects it instead of clamping. Physical mapping
    keeps points in bounds on a consistent pyramid, so the run level's translation is shifted here
    to force the case. Fails before segmentation, so no SAM2 is needed.
    """
    store, (cx, cy), frame = single_blob_zarr
    coarsest = OmeZarrReader(store).n_levels - 1
    real = OmeZarrReader.level_transform

    def shifted(self, level):
        scale, translation = real(self, level)
        if level == coarsest:
            translation = (translation[0], translation[1], translation[2] - 1000.0)
        return scale, translation

    monkeypatch.setattr(OmeZarrReader, "level_transform", shifted)
    prompts = _prompts(tmp_path / "edge.json", frame, [cx, cy], level=0)
    out = tmp_path / "edge.ome.zarr"

    code = _run(store, out, prompts, coarsest)

    assert code == 1
    assert not out.exists()


@pytest.mark.real_backend
@requires_sam2
def test_anisotropic_pyramid_converts_each_axis_by_its_own_ratio(tmp_path):
    """Acceptance Scenario 3/FR-004: the sweep axis and the in-plane axes may downsample by
    different factors between levels; conversion must use each axis's own ratio, not one scalar.
    """
    # level1's in-plane shape must stay large enough for SAM2 to segment meaningfully (8x8,
    # matching the smallest in-plane size already proven to work elsewhere in this file) --
    # with a 4x in-plane downsample that means a 32x32 level-0 frame, not 16x16.
    vol = np.zeros((8, 32, 32), np.uint8)
    vol[2:6, 8:24, 8:24] = 200
    # z (sweep axis) halves per level; y/x (in-plane) quarter per level -- deliberately different
    store = write_ome_zarr(tmp_path / "aniso.ome.zarr", vol, axis_factors=(2, 4, 4))
    reader = OmeZarrReader(store)
    level0_shape, level1_shape = reader.level_shape(0), reader.level_shape(1)

    converted_out = tmp_path / "converted.ome.zarr"
    converted_prompts = _prompts(tmp_path / "p0.json", 4, [16, 16], level=0)
    assert _run(store, converted_out, converted_prompts, 1) == 0

    x_ratio = level1_shape[2] / level0_shape[2]
    y_ratio = level1_shape[1] / level0_shape[1]
    z_ratio = level1_shape[0] / level0_shape[0]
    native_xy = [round(16 * x_ratio), round(16 * y_ratio)]
    native_frame = round(4 * z_ratio)
    native_out = tmp_path / "native.ome.zarr"
    native_prompts = _prompts(tmp_path / "p1.json", native_frame, native_xy, level=1)
    assert _run(store, native_out, native_prompts, 1) == 0

    rconv, rnative = OmeZarrReader(converted_out), OmeZarrReader(native_out)
    assert (rconv.read_level(1) == rnative.read_level(1)).all()
    assert rconv.read_level(1).any()


# -- feature 008-level-agnostic-prompts: unknown authoring level (US3) --------------------------


def test_unknown_authoring_level_reports_available_and_leaves_no_output(
    single_blob_zarr, tmp_path, capsys
):
    """US3 Acceptance Scenario 1 / C-PF-4: the prompt file's own "level" (not the run's --level)
    referencing a level this input doesn't have fails clearly, distinct from an invalid --level.
    """
    store, (cx, cy), frame = single_blob_zarr
    out = tmp_path / "unknown_level.ome.zarr"
    prompts = _prompts(tmp_path / "p.json", frame, [cx, cy], level=99)

    code = _run(store, out, prompts, 0)

    assert code == 1
    assert not out.exists()
    assert "available levels" in capsys.readouterr().err
