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


class _PreviewBusyGuard:
    """Tracks whether a single-slice/few-slices preview computation is in flight (feature 007).

    Pure and display-independent -- unlike the rest of :meth:`InteractiveSession.launch`'s GUI
    wiring, this is unit-tested directly (research R4). Guards FR-011: while busy, a new preview
    trigger is a no-op rather than being queued or cancelling the in-flight one.
    """

    def __init__(self) -> None:
        self.busy = False

    def try_start(self) -> bool:
        """Return ``True`` and mark busy if idle; return ``False`` (no-op) if already busy."""
        if self.busy:
            return False
        self.busy = True
        return True

    def finish(self) -> None:
        """Clear busy state, e.g. from a `thread_worker`'s ``returned``/``errored`` signal."""
        self.busy = False


def _clip_window(current: int, half_width: int, n_frames: int) -> tuple[int, int]:
    """The few-slices window: ``current`` ± ``half_width``, clipped to ``[0, n_frames)`` (FR-004).

    Pure and display-independent, unit-tested directly (research R4).
    """
    start = max(0, current - half_width)
    end = min(n_frames - 1, current + half_width)
    return start, end


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
        # at most one box per frame (feature 006, FR-010): frame_index -> [x0, y0, x1, y1]
        self._boxes: dict[int, np.ndarray] = {}
        self._preview: MaskResult | None = None
        self._last_preview_kwargs: dict = {}

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

    def add_box(self, frame_index: int, box) -> InteractiveSession:  # noqa: ANN001
        """Set (replacing any existing) the box prompt for ``frame_index`` (feature 006, FR-010)."""
        self._boxes[int(frame_index)] = np.asarray(box, dtype=float)
        self._preview = None
        return self

    def clear_boxes(self) -> InteractiveSession:
        self._boxes = {}
        self._preview = None
        return self

    # -- preview & export -------------------------------------------------
    def preview(
        self,
        axes: list[str] | None = None,
        direction: str = "forward",
        combine_rule: str = "majority",
        postprocess: PostProcessConfig | None = None,
        frame_range: tuple[int, int] | None = None,
    ) -> MaskResult:
        """Run the shared engine on the current prompts and cache the resulting mask.

        ``frame_range`` restricts computation to an inclusive range of frames on the prompted axis
        (feature 007's single-slice/few-slices preview modes); ``None`` (default) sweeps the full
        volume, unchanged from before.
        """
        self._predictor.clear_prompts()
        by_frame: dict[int, tuple[list[list[float]], list[int]]] = {}
        for frame, x, y, label in self._points:
            coords, labels = by_frame.setdefault(frame, ([], []))
            coords.append([x, y])
            labels.append(label)
        # Merge each frame's points and box into ONE add_prompts(..., box=...) call
        # (feature 006, research R2): SAM2 silently drops one or the other if they're two
        # separate calls.
        for frame in sorted(set(by_frame) | set(self._boxes)):
            coords, labels = by_frame.get(frame, ([], []))
            self._predictor.add_prompts(
                frame_index=frame,
                point_coords=coords,
                point_labels=labels,
                box=self._boxes.get(frame),
            )
        # Remembered so export() can force a full recompute (frame_range=None) while preserving
        # whatever axes/direction/combine_rule/postprocess the caller last configured (FR-008).
        self._last_preview_kwargs = {
            "axes": axes,
            "direction": direction,
            "combine_rule": combine_rule,
            "postprocess": postprocess,
        }
        self._preview = self._predictor.predict(
            axes=axes,
            direction=direction,
            combine_rule=combine_rule,
            postprocess=postprocess,
            frame_range=frame_range,
        )
        return self._preview

    def export(self, output_path: str | Path, overwrite: bool = False) -> Path:
        """Write the full whole-volume mask to OME-Zarr v0.5, always recomputing it fresh.

        Never reuses a cached ``self._preview`` (feature 007, FR-008/C-PV-9): a prior
        single-slice/few-slices preview may only cover a partial ``frame_range``, and exporting
        that partial result instead of the full volume would be silently wrong. Preserves whatever
        axes/direction/combine_rule/postprocess the last ``preview()`` call used, if any.
        """
        self.preview(frame_range=None, **self._last_preview_kwargs)
        return self._preview.save(output_path, overwrite=overwrite)

    def read_volume(self) -> np.ndarray:
        """The run-level volume, for display."""
        reader = OmeZarrReader(self._store_path)
        return reader.read_level(reader.resolve_level(self._level))

    # -- napari view ------------------------------------------------------
    def launch(self) -> None:  # pragma: no cover - requires napari + a display
        """Open a napari viewer wired to this session (requires the ``[interactive]`` extra).

        Adds the volume as an image layer and three prompt layers (feature 006):
        ``positive-points`` (lime crosses), ``negative-points`` (red discs), and ``positive-box``
        (a translucent, lime-outlined rectangle-only layer). New points default to positive; select
        one or more and press ``n``/``y`` to flip them between the two point layers -- the flip
        leaves the point selected in its new layer so an immediate opposite keypress flips it right
        back, and switching which layer you're interacting with clears the layer you left so a
        forgotten selection can't bleed into a later keypress (FR-003/004/004a/004b). Three preview
        shortcuts (feature 007): ``s`` (single-slice, current frame only), ``f`` (few-slices, a
        fixed ±5-frame window around the current slice), and ``p`` (whole-volume, gated behind a
        confirmation since it's the expensive one). ``s``/``f`` run asynchronously with a
        status-bar busy indicator and ignore a repeat trigger while already computing
        (FR-010/FR-011). ``e`` exports the full whole-volume mask, always freshly computed
        regardless of the last preview mode (FR-008). All masking goes through the shared engine.
        """
        from napari.qt.threading import thread_worker
        from qtpy.QtCore import QTimer
        from qtpy.QtWidgets import QMessageBox

        napari = _require_napari()

        volume = self.read_volume()
        viewer = napari.Viewer()
        viewer.add_image(volume, name="volume")

        positive_layer = viewer.add_points(
            name="positive-points",
            ndim=3,
            symbol="cross",
            size=7,
            face_color="lime",
            border_width=0,
        )
        negative_layer = viewer.add_points(
            name="negative-points",
            ndim=3,
            symbol="disc",
            size=6,
            face_color="red",
            border_width=0,
        )
        box_layer = viewer.add_shapes(
            name="positive-box",
            ndim=3,
            blending="translucent_no_depth",
            opacity=1.0,
            edge_color="lime",
            edge_width=1,
            face_color="#00000000",
        )

        def _enforce_box_layer_rules(event=None) -> None:  # noqa: ANN001, ARG001
            """Rectangle-only, at most one box per frame (feature 006, FR-007/FR-010).

            Deferred via ``QTimer.singleShot(0, ...)`` rather than mutating ``box_layer``
            synchronously inside its own ``data`` event handler: doing it synchronously causes
            napari/Qt to re-enter its own layer-change machinery and blow the recursion limit
            (confirmed while implementing this feature). A zero-delay deferral runs right after
            the current event finishes, imperceptible to the user, and avoids the reentrancy.
            """

            def _fix() -> None:
                shape_types = list(box_layer.shape_type)
                non_rectangle = [i for i, t in enumerate(shape_types) if t != "rectangle"]
                if non_rectangle:
                    box_layer.selected_data = set(non_rectangle)
                    box_layer.remove_selected()
                    return  # re-triggers this handler via the data event

                data = box_layer.data
                if len(data) < 2:
                    return
                last_index_per_frame: dict[int, int] = {}
                for i, verts in enumerate(data):
                    frame = int(round(float(verts[0][0])))
                    last_index_per_frame[frame] = i  # a later index is the newest draw/edit
                keep = set(last_index_per_frame.values())
                stale = [i for i in range(len(data)) if i not in keep]
                if stale:
                    box_layer.selected_data = set(stale)
                    box_layer.remove_selected()

            QTimer.singleShot(0, _fix)

        box_layer.events.data.connect(_enforce_box_layer_rules)

        def _flip_selected(source, dest) -> None:  # noqa: ANN001
            selected = list(source.selected_data)
            if not selected:
                return
            moved_coords = source.data[selected].copy()
            source.remove_selected()
            dest.add(moved_coords)  # napari auto-selects newly added points (FR-004b)

        @viewer.bind_key("n")
        def _mark_negative(_viewer):  # noqa: ANN001
            _flip_selected(positive_layer, negative_layer)

        @viewer.bind_key("y")
        def _mark_positive(_viewer):  # noqa: ANN001
            _flip_selected(negative_layer, positive_layer)

        _previously_active = viewer.layers.selection.active

        def _on_active_layer_changed(event) -> None:  # noqa: ANN001
            nonlocal _previously_active
            old, new = _previously_active, event.value
            if old is not None and old is not new and old in (positive_layer, negative_layer):
                old.selected_data = set()  # FR-004a: don't let a stale selection bleed forward
            _previously_active = new

        viewer.layers.selection.events.active.connect(_on_active_layer_changed)

        def _sync_points_from_layer() -> None:
            self.clear_points()
            for z, y, x in positive_layer.data:
                self.add_point(int(round(z)), float(x), float(y), positive=True)
            for z, y, x in negative_layer.data:
                self.add_point(int(round(z)), float(x), float(y), positive=False)

        def _sync_boxes_from_layer() -> None:
            self.clear_boxes()
            for verts in box_layer.data:
                frame = int(round(float(verts[0][0])))
                y0, x0 = float(verts[:, 1].min()), float(verts[:, 2].min())
                y1, x1 = float(verts[:, 1].max()), float(verts[:, 2].max())
                self.add_box(frame, [x0, y0, x1, y1])

        def _sync_prompts_from_layers() -> None:
            _sync_points_from_layer()
            _sync_boxes_from_layer()

        n_frames = volume.shape[0]
        busy_guard = _PreviewBusyGuard()

        def _merge_into_preview_layer(array: np.ndarray, frame_range: tuple[int, int]) -> None:
            """Write ``array`` into the shared preview layer at only ``frame_range`` (research R3).

            Every other frame keeps whatever it already held; the layer is created zero-filled at
            the full volume shape first if it doesn't exist yet.
            """
            data = array.astype(np.uint8)
            start, end = frame_range
            if "preview" in viewer.layers:
                layer = viewer.layers["preview"]
                merged = layer.data.copy()
                merged[start : end + 1] = data[start : end + 1]
                layer.data = merged
            else:
                viewer.add_labels(data, name="preview")

        def _run_async_preview(frame_range: tuple[int, int], busy_message: str) -> None:
            if not busy_guard.try_start():  # FR-011: ignore a trigger while one is in flight
                return
            _sync_prompts_from_layers()
            start, end = frame_range
            has_point = any(start <= p[0] <= end for p in self._points)
            has_box = any(start <= f <= end for f in self._boxes)
            if not (has_point or has_box):
                busy_guard.finish()
                viewer.status = "preview: no prompts on the requested frame(s)"
                return

            @thread_worker
            def _compute():
                return self.preview(axes=["z"], frame_range=frame_range)

            def _on_done(result) -> None:  # noqa: ANN001
                busy_guard.finish()
                viewer.status = ""
                _merge_into_preview_layer(result.array, frame_range)

            def _on_error(exc: Exception) -> None:
                busy_guard.finish()
                viewer.status = f"preview failed: {exc}"

            viewer.status = busy_message
            worker = _compute()
            worker.returned.connect(_on_done)
            worker.errored.connect(_on_error)

        @viewer.bind_key("s")
        def _preview_single_slice(_viewer):  # noqa: ANN001
            current = int(viewer.dims.current_step[0])
            _run_async_preview((current, current), "computing single-slice preview...")

        @viewer.bind_key("f")
        def _preview_few_slices(_viewer):  # noqa: ANN001
            current = int(viewer.dims.current_step[0])
            window = _clip_window(current, half_width=5, n_frames=n_frames)
            _run_async_preview(window, "computing few-slices preview...")

        @viewer.bind_key("p")
        def _preview_whole_volume(_viewer):  # noqa: ANN001
            answer = QMessageBox.question(
                None,
                "Whole-volume preview",
                "This recomputes the mask across the entire volume and can take several minutes "
                "on real data. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            _sync_prompts_from_layers()
            result = self.preview(axes=["z"])
            _merge_into_preview_layer(result.array, (0, n_frames - 1))

        @viewer.bind_key("e")
        def _export(_viewer):  # noqa: ANN001
            _sync_prompts_from_layers()
            self.export("interactive_output.ome.zarr", overwrite=True)

        napari.run()


def _require_napari():
    """Import napari or raise a clear, actionable error (the ``[interactive]`` extra)."""
    try:
        import napari
    except Exception as exc:  # noqa: BLE001
        raise ImportError(
            "the interactive session requires the '[interactive]' extra (napari + Qt). "
            "Install it with: pip install 'ome-zarr-masker[interactive]'"
        ) from exc
    return napari


__all__ = ["InteractiveSession"]
