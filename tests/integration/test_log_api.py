"""T016: API-supplied prompts are logged with prompt_source="api" and the run id is exposed.

Covers C-LOG-API-1 (api source + full prompts), C-LOG-API-3 (run id == log == record),
and C-LOG-API-2 (a failed predict still writes a log).
"""

from __future__ import annotations

import json

import pytest

from organ_masker_lite import OrganMaskPredictor
from organ_masker_lite.prompts.model import PromptError

from ..conftest import sam2_available

_HAVE_SAM2 = sam2_available()


@pytest.mark.real_backend
@pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")
def test_api_predict_logs_prompts_and_exposes_runid(single_blob_zarr, tmp_path):
    store, (cx, cy), frame = single_blob_zarr
    logdir = tmp_path / "logs"
    predictor = OrganMaskPredictor(log_dir=logdir).set_volume(store, level=0)
    predictor.add_prompts(frame_index=frame, point_coords=[[cx, cy]], point_labels=[1])
    result = predictor.predict(axes=["z"])

    log = next(logdir.glob("*.log"))
    text = log.read_text()
    assert "command: api" in text
    assert "prompt_source: api" in text
    assert "prompt_count: 1" in text
    assert result.run_id is not None
    assert log.stem == result.run_id
    assert f"run_id: {result.run_id}" in text

    # the same run id is embedded in the saved output run-record (FR-005)
    out = result.save(tmp_path / "out.ome.zarr")
    assert json.loads((out / "run_record.json").read_text())["run_id"] == result.run_id


def test_failed_api_predict_still_writes_log(single_blob_zarr, tmp_path):
    store, (cx, cy), _frame = single_blob_zarr
    logdir = tmp_path / "logs"
    predictor = OrganMaskPredictor(log_dir=logdir).set_volume(store, level=0)
    # bad frame
    predictor.add_prompts(frame_index=9999, point_coords=[[cx, cy]], point_labels=[1])
    with pytest.raises(PromptError):
        predictor.predict(axes=["z"])
    log = next(logdir.glob("*.log"))
    assert "outcome: failed" in log.read_text()
