"""T017: a large prompt set is captured in full with the count in the header (feature 002)."""

from __future__ import annotations

from ome_zarr_masker.config import LogConfig
from ome_zarr_masker.input_log import log_invocation
from ome_zarr_masker.prompts.model import Prompt, PromptSet


def test_large_prompt_set_recorded_in_full(tmp_path):
    prompts = PromptSet(
        [
            Prompt(
                frame_index=i,
                point_coords=[[float(i), float(i)]],
                point_labels=[1],
                obj_id=i,
            )
            for i in range(50)
        ]
    )
    cfg = LogConfig(log_dir=tmp_path / "logs")
    with log_invocation("cmd", cfg) as log:
        log.record_prompts(prompts, source="api")
        path = log.path
    text = path.read_text()
    assert "prompt_count: 50" in text
    for i in range(50):
        assert f"frame_index={i}" in text
