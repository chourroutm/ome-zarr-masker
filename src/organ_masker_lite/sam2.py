"""SAM2 video-predictor adapter — the project's only segmentation implementation.

Imports of ``torch``/``sam2`` are deferred to construction so the package works without those
heavy, optional dependencies installed unless actually segmenting. Install with the ``[sam2]``
extra to use it.

The predictor is built from a Hydra config name and a checkpoint file (FR-019/FR-020): the
checkpoint is resolved against the run's model directory and auto-downloaded on first use unless
downloads are disabled. The defaults target the SAM2.1 Hiera-Large variant; override the config
name / checkpoint via ``ORGAN_MASKER_SAM2_CONFIG`` / ``ORGAN_MASKER_SAM2_CHECKPOINT`` if your
installed ``sam2`` build ships different config paths.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import nullcontext
from pathlib import Path

import numpy as np

from .config import RunConfig
from .prompts.model import PromptSet

#: Default SAM2.1 Hiera-Large variant. The config name is resolved by sam2's bundled Hydra search
#: path; the checkpoint filename lives in the run's model directory.
_DEFAULT_CONFIG = "configs/sam2.1/sam2.1_hiera_l.yaml"
_DEFAULT_CHECKPOINT = "sam2.1_hiera_large.pt"
_CHECKPOINT_URL = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"

_CONFIG_ENV = "ORGAN_MASKER_SAM2_CONFIG"
_CHECKPOINT_ENV = "ORGAN_MASKER_SAM2_CHECKPOINT"


class Sam2Backend:
    """Adapter over SAM2's video predictor (``build_sam2_video_predictor``)."""

    def __init__(self, config: RunConfig | None = None):
        self._config = config if config is not None else RunConfig()
        try:
            import torch
            from sam2.build_sam import build_sam2_video_predictor
        except Exception as exc:  # noqa: BLE001
            raise ImportError(
                "SAM2 requires the '[sam2]' extra (torch + sam2). Install it with: "
                "pip install 'organ-masker-lite[sam2]'"
            ) from exc
        self._torch = torch
        self._build = build_sam2_video_predictor
        self._config_name = os.environ.get(_CONFIG_ENV, _DEFAULT_CONFIG)
        self._predictor = None  # built lazily on first segmentation, then reused

    def _resolve_checkpoint(self) -> Path:
        """Resolve the checkpoint path, downloading it on first use unless disabled (FR-019/020)."""
        filename = os.environ.get(_CHECKPOINT_ENV, _DEFAULT_CHECKPOINT)
        return self._config.resolve_weight(filename, _CHECKPOINT_URL, description="SAM2 checkpoint")

    def _get_predictor(self):
        """Build the video predictor once (config + checkpoint + device) and cache it."""
        if self._predictor is None:
            device = "cuda" if self._torch.cuda.is_available() else "cpu"
            ckpt = self._resolve_checkpoint()
            self._predictor = self._build(self._config_name, str(ckpt), device=device)
        return self._predictor

    def segment_video(
        self, frames: np.ndarray, prompts: PromptSet
    ) -> np.ndarray:  # pragma: no cover
        """Propagate a mask across ``frames`` using SAM2's video predictor.

        Frames are materialised to a temporary JPEG directory (the SAM2-native input form),
        prompts are added on their frames via ``add_new_points_or_box`` using the encoder's
        ``(coords, labels, box)`` convention, then ``propagate_in_video`` fills the stack.
        """
        from PIL import Image as PILImage

        torch = self._torch
        n_frames, height, width = frames.shape[:3]
        predictor = self._get_predictor()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        with tempfile.TemporaryDirectory() as frame_dir:
            for i in range(n_frames):
                PILImage.fromarray(frames[i]).save(Path(frame_dir) / f"{i:05d}.jpg")
            autocast = (
                torch.autocast("cuda", dtype=torch.bfloat16) if device == "cuda" else nullcontext()
            )
            out = np.zeros((n_frames, height, width), dtype=bool)
            with torch.inference_mode(), autocast:
                state = predictor.init_state(video_path=frame_dir)
                obj_id = 0
                for p in prompts.prompts:
                    kwargs: dict = {
                        "inference_state": state,
                        "frame_idx": p.frame_index,
                        "obj_id": obj_id,
                    }
                    if p.point_coords.size:
                        kwargs["points"] = p.point_coords.astype("float32")
                        kwargs["labels"] = p.point_labels.astype("int32")
                    if p.box is not None:
                        kwargs["box"] = p.box.astype("float32")
                    predictor.add_new_points_or_box(**kwargs)
                for frame_idx, _obj_ids, mask_logits in predictor.propagate_in_video(state):
                    out[frame_idx] = (mask_logits[0] > 0).cpu().numpy().reshape(height, width)
        return out
