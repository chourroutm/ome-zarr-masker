"""Interactive masking session (FR-009, FR-011), built on the shared engine via the predictor.

The :class:`InteractiveSession` core -- prompt state, preview, and export -- is fully usable and
testable without napari. :meth:`InteractiveSession.launch` is a thin napari view over that core and
lazily imports napari (the optional ``[interactive]`` extra), so importing this module never pulls
in napari/Qt.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .api import MaskResult, OrganMaskPredictor
from .config import COARSEST_LEVEL, PostProcessConfig
from .io.reader import OmeZarrReader


class InteractiveSession:
    """Headless core of the interactive workflow over a single volume."""

    def __init__(
        self,
        store_path: str | Path,
        level: int = COARSEST_LEVEL,
        model_dir: str | Path | None = None,
        allow_download: bool = True,
        *,
        predictor: OrganMaskPredictor | None = None,
    ):
        self._store_path = str(store_path)
        self._level = level
        self._predictor = predictor or OrganMaskPredictor(
            model_dir=model_dir, allow_download=allow_download
        )
        self._predictor.set_volume(store_path, level=level)
        # prompt points as (frame_index, x, y, label) with label 1=positive, 0=negative
        self._points: list[tuple[int, float, float, int]] = []
        self._preview: MaskResult | None = None

    # -- prompt placement -------------------------------------------------
    def add_point(
        self, frame_index: int, x: float, y: float, positive: bool = True
    ) -> InteractiveSession:
        self._points.append((int(frame_index), float(x), float(y), 1 if positive else 0))
        self._preview = None  # invalidate stale preview
        return self

    def add_positive_point(self, frame_index: int, x: float, y: float) -> InteractiveSession:
        return self.add_point(frame_index, x, y, positive=True)

    def add_negative_point(self, frame_index: int, x: float, y: float) -> InteractiveSession:
        return self.add_point(frame_index, x, y, positive=False)

    def clear_points(self) -> InteractiveSession:
        self._points = []
        self._preview = None
        return self

    # -- preview & export -------------------------------------------------
    def preview(
        self,
        axes: list[str] | None = None,
        direction: str = "forward",
        combine_rule: str = "majority",
        postprocess: PostProcessConfig | None = None,
    ) -> MaskResult:
        """Run the shared engine on the current prompts and cache the resulting mask."""
        self._predictor.clear_prompts()
        by_frame: dict[int, tuple[list[list[float]], list[int]]] = {}
        for frame, x, y, label in self._points:
            coords, labels = by_frame.setdefault(frame, ([], []))
            coords.append([x, y])
            labels.append(label)
        for frame, (coords, labels) in sorted(by_frame.items()):
            self._predictor.add_points(frame_index=frame, point_coords=coords, point_labels=labels)
        self._preview = self._predictor.predict(
            axes=axes, direction=direction, combine_rule=combine_rule, postprocess=postprocess
        )
        return self._preview

    def export(self, output_path: str | Path, overwrite: bool = False) -> Path:
        """Write the current preview to OME-Zarr v0.5 (computing one first if needed)."""
        if self._preview is None:
            self.preview()
        return self._preview.save(output_path, overwrite=overwrite)

    def read_volume(self) -> np.ndarray:
        """The run-level volume, for display."""
        reader = OmeZarrReader(self._store_path)
        return reader.read_level(reader.resolve_level(self._level))

    # -- napari view ------------------------------------------------------
    def launch(self) -> None:  # pragma: no cover - requires napari + a display
        """Open a napari viewer wired to this session (requires the ``[interactive]`` extra).

        Adds the volume as an image layer and a points layer for landmarks; pressing ``p`` previews
        the mask for the current points (positive vs negative read from each point's ``positive``
        feature) and ``e`` exports it. All masking goes through the shared engine (FR-011).
        """
        napari = _require_napari()

        volume = self.read_volume()
        viewer = napari.Viewer()
        viewer.add_image(volume, name="volume")
        points_layer = viewer.add_points(
            name="prompts", ndim=3, features={"positive": np.array([], dtype=bool)}
        )

        def _sync_points_from_layer() -> None:
            self.clear_points()
            positive = points_layer.features.get("positive", [])
            for (z, y, x), pos in zip(points_layer.data, positive, strict=False):
                self.add_point(int(round(z)), float(x), float(y), positive=bool(pos))

        @viewer.bind_key("p")
        def _preview(_viewer):  # noqa: ANN001
            _sync_points_from_layer()
            result = self.preview()
            if "preview" in viewer.layers:
                viewer.layers["preview"].data = result.array.astype(np.uint8)
            else:
                viewer.add_labels(result.array.astype(np.uint8), name="preview")

        @viewer.bind_key("e")
        def _export(_viewer):  # noqa: ANN001
            _sync_points_from_layer()
            self.export("interactive_output.ome.zarr", overwrite=True)

        napari.run()


def _require_napari():
    """Import napari or raise a clear, actionable error (the ``[interactive]`` extra)."""
    try:
        import napari
    except Exception as exc:  # noqa: BLE001
        raise ImportError(
            "the interactive session requires the '[interactive]' extra (napari + Qt). "
            "Install it with: pip install 'organ-masker-lite[interactive]'"
        ) from exc
    return napari


__all__ = ["InteractiveSession"]
