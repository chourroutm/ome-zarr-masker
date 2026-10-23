"""Post-processing steps in the interactive session and in prompt files (feature 011, T022/T029).

SAM2 is replaced by a stub (foreground = bright voxels). Covers US3 (panel steps saved with the
prompts and reused by ``mask``, SC-007) and US4 (post-processing files, parity across sources,
reproducibility from the run record: SC-004, SC-005).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from ome_zarr_masker.api import OrganMaskPredictor
from ome_zarr_masker.cli import main
from ome_zarr_masker.interactive import InteractiveSession
from ome_zarr_masker.io.reader import OmeZarrReader
from ome_zarr_masker.postprocess.steps import PostProcessError, parse_steps
from ome_zarr_masker.prompts.model import load_prompt_file

from ..conftest import StubBackend, write_ome_zarr


@pytest.fixture(autouse=True)
def stub_sam2(monkeypatch):
    from ome_zarr_masker.engine import pipeline

    monkeypatch.setattr(pipeline, "Sam2Backend", lambda config=None: StubBackend())


@pytest.fixture
def store(tmp_path):
    """Two blobs joined by nothing, with a hole: `largest` and `fill` both change the mask."""
    vol = np.zeros((16, 32, 32), np.uint8)
    vol[2:14, 4:20, 4:20] = 200
    vol[6:10, 9:15, 9:15] = 0  # an enclosed hole
    vol[4:12, 24:28, 24:28] = 200  # a smaller separate blob
    return write_ome_zarr(tmp_path / "in.ome.zarr", vol, n_levels=2)


def _session(store, prompts_path, **kw) -> InteractiveSession:
    s = InteractiveSession(store, level=0, prompts_path=prompts_path, **kw)
    if not s.has_prompts:
        s.add_positive_point(8, 12.0, 12.0)
    return s


def _level0(out) -> np.ndarray:
    return OmeZarrReader(out).read_level(0)


# -- US3: session steps, saved with the prompts -------------------------------------------------


def test_session_steps_set_saved_and_reused_by_mask(store, tmp_path):
    p = tmp_path / "prompts.json"
    s = _session(store, p, postprocess="close:1,fill")
    assert s.postprocess.text() == "close:1,fill"

    with pytest.raises(PostProcessError):
        s.set_postprocess("blur:3")
    assert s.postprocess.text() == "close:1,fill"  # an invalid edit keeps the previous steps

    s.set_postprocess("close:1,fill,largest")
    export = s.export(tmp_path / "export.ome.zarr")
    assert s.save_prompts() == p
    saved = load_prompt_file(p)
    assert saved.postprocess == parse_steps("close:1,fill,largest").steps  # the final values
    assert saved.level == 0

    out = tmp_path / "mask.ome.zarr"
    assert main(["mask", str(store), str(out), "--prompts", str(p), "--level", "0"]) == 0
    np.testing.assert_array_equal(_level0(out), _level0(export))  # SC-007
    rec = json.loads((out / "run_record.json").read_text())["config"]["postprocess"]
    assert rec["source"] == "prompt_file"


def test_preview_uses_session_steps_like_predict(store, tmp_path):
    s = _session(store, tmp_path / "p.json", postprocess="fill,largest")
    p = OrganMaskPredictor().set_volume(store, level=0)
    p.add_prompts(frame_index=8, point_coords=[[12.0, 12.0]], point_labels=[1])
    np.testing.assert_array_equal(s.preview().array, p.predict(postprocess="fill,largest").array)
    raw = s.preview(postprocess="none").array
    assert not np.array_equal(raw, s.preview().array)  # the session's steps changed the mask


def test_reopened_session_loads_prompts_and_saved_steps(store, tmp_path):
    p = tmp_path / "prompts.json"
    first = _session(store, p, postprocess="fill")
    first.add_negative_point(8, 2.0, 2.0)
    first.add_box(9, [4, 4, 20, 20])
    first.save_prompts()

    again = InteractiveSession(store, level=0, prompts_path=p)
    assert again.postprocess.text() == "fill" and again.postprocess.source == "prompt_file"
    assert sorted(again.points) == sorted(first.points)
    assert {f: b.tolist() for f, b in again.boxes.items()} == {9: [4.0, 4.0, 20.0, 20.0]}

    coarse = InteractiveSession(store, level=1, prompts_path=p)  # converted to its level
    assert sorted(f for f, *_ in coarse.points) == [4, 4]
    assert coarse.postprocess.text() == "fill"


def test_session_without_saved_steps_has_none(store, tmp_path):
    s = _session(store, tmp_path / "missing.json")
    assert s.postprocess.steps == () and s.postprocess.source == "default"


def test_interactive_cli_rejects_bad_steps_before_opening(store, tmp_path, monkeypatch, capsys):
    launched = []
    monkeypatch.setattr(InteractiveSession, "launch", lambda self: launched.append(self))
    code = main(["interactive", str(store), "--postprocess", "blur:3"])
    assert code == 1 and launched == [] and "blur:3" in capsys.readouterr().err

    p = tmp_path / "p.json"
    assert main(["interactive", str(store), "--prompts", str(p), "--postprocess", "fill"]) == 0
    (session,) = launched
    assert session.prompts_path == p and session.postprocess.text() == "fill"
