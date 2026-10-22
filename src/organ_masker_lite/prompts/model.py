"""SAM2-compatible landmark prompts.

Mirrors the SAM2 prompt-encoder convention: point coordinates are ``(x, y)`` in slice pixel
space, labels are ``1`` (positive/include) or ``0`` (negative/exclude); an optional box is
``[x_min, y_min, x_max, y_max]``. Box-corner labels (2/3) and padding (-1) are produced
internally by the backend and are never supplied here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..geometry import nearest_index

#: A pyramid level's ``(scale, translation)``, one value per axis.
LevelGeometry = tuple[tuple[float, ...], tuple[float, ...]]


class PromptError(ValueError):
    """Raised when a prompt or prompt set is invalid."""


def _same_geometry(a: LevelGeometry, b: LevelGeometry) -> bool:
    return tuple(map(tuple, a)) == tuple(map(tuple, b))


@dataclass
class Prompt:
    """Landmark prompts placed on one slice/frame for one object."""

    frame_index: int
    point_coords: np.ndarray  # (N, 2) float, (x, y)
    point_labels: np.ndarray  # (N,) int in {0, 1}
    box: np.ndarray | None = None  # (4,) float [x0, y0, x1, y1]
    obj_id: int = 0

    def __post_init__(self) -> None:
        self.point_coords = np.asarray(self.point_coords, dtype=float).reshape(-1, 2)
        self.point_labels = np.asarray(self.point_labels, dtype=int).reshape(-1)
        if self.point_coords.shape[0] != self.point_labels.shape[0]:
            raise PromptError("point_coords and point_labels must have the same length")
        if self.point_labels.size and not np.isin(self.point_labels, (0, 1)).all():
            raise PromptError("point_labels must be 0 (exclude) or 1 (include)")
        if self.box is not None:
            self.box = np.asarray(self.box, dtype=float).reshape(4)

    @property
    def positive_coords(self) -> np.ndarray:
        return self.point_coords[self.point_labels == 1]

    @property
    def negative_coords(self) -> np.ndarray:
        return self.point_coords[self.point_labels == 0]


@dataclass
class PromptSet:
    """A collection of prompts for one run (single target structure, FR-021).

    ``level`` is the pyramid level these prompts' coordinates were authored against (feature
    008-level-agnostic-prompts, FR-002); ``None`` means "already in whatever level this set is
    used at" -- the default for prompt sets not produced by one of the two authoring paths
    (a loaded prompt file, or the ``OrganMaskPredictor`` API), e.g. internal/test construction and
    pipeline-internal seed prompts for secondary sweep axes.
    """

    prompts: list[Prompt] = field(default_factory=list)
    level: int | None = None

    def has_positive(self) -> bool:
        return any(p.point_labels.tolist().count(1) or p.box is not None for p in self.prompts)

    def resolved_between(
        self, src_geometry: LevelGeometry, dst_geometry: LevelGeometry, axis_index: int
    ) -> PromptSet:
        """Convert every prompt from one level's pixel grid to another's by physical position.

        Each geometry is ``(scale, translation)`` per axis, from the level's OME-Zarr
        ``coordinateTransformations``. Every coordinate (frame index, point, box corner) goes to its
        physical position on the source level and snaps to the nearest pixel centre on the target
        level, exact ties to the lower pixel -- the same rule the mask writer uses (FR-004).
        Returns ``self`` when both geometries match (FR-006). ``axis_index`` is the sweep axis; the
        other two axes are "height" and "width" in the order :meth:`validate` uses.
        """
        if _same_geometry(src_geometry, dst_geometry):
            return self
        (src_scale, src_trans), (dst_scale, dst_trans) = src_geometry, dst_geometry
        remaining = [i for i in range(len(src_scale)) if i != axis_index]
        height_axis, width_axis = remaining[0], remaining[1]

        def along(axis: int, values: np.ndarray) -> np.ndarray:
            return nearest_index(
                values, src_scale[axis], src_trans[axis], dst_scale[axis], dst_trans[axis]
            )

        # One vectorised call per axis across all prompts keeps large sets within the budget.
        frames = along(axis_index, np.array([p.frame_index for p in self.prompts]))
        counts = [p.point_coords.shape[0] for p in self.prompts]
        points = (
            np.concatenate([p.point_coords for p in self.prompts])
            if self.prompts
            else np.empty((0, 2))
        )
        points = np.column_stack(
            [along(width_axis, points[:, 0]), along(height_axis, points[:, 1])]
        ).astype(float)
        point_groups = np.split(points, np.cumsum(counts)[:-1]) if self.prompts else []
        boxed = [i for i, p in enumerate(self.prompts) if p.box is not None]
        boxes = {}
        if boxed:
            b = np.stack([self.prompts[i].box for i in boxed])
            converted = np.column_stack(
                [
                    along(width_axis, b[:, 0]),
                    along(height_axis, b[:, 1]),
                    along(width_axis, b[:, 2]),
                    along(height_axis, b[:, 3]),
                ]
            ).astype(float)
            boxes = dict(zip(boxed, converted, strict=True))

        out = []
        for i, p in enumerate(self.prompts):
            # Bypass Prompt's validating __init__/__post_init__: these values are already valid
            # (same shapes, same labels, box already a (4,) float array) by construction, and
            # re-validating them dominates cost for large prompt sets (plan.md's perf budget).
            new = Prompt.__new__(Prompt)
            new.frame_index = int(frames[i])
            new.point_coords = point_groups[i].reshape(-1, 2)
            new.point_labels = p.point_labels
            new.box = boxes.get(i)
            new.obj_id = p.obj_id
            out.append(new)
        return PromptSet(prompts=out, level=self.level)

    def validate(self, level_shape: tuple[int, ...], axis_index: int) -> None:
        """Validate prompts against the selected level (FR-015).

        ``level_shape`` is the (z, y, x) shape of the run level; ``axis_index`` is the sweep
        axis. Coordinates are checked against the in-plane dimensions of that axis.
        """
        if not self.has_positive():
            raise PromptError("at least one positive point or a box is required")
        plane = [d for i, d in enumerate(level_shape) if i != axis_index]
        height, width = plane[0], plane[1]
        n_frames = level_shape[axis_index]
        for p in self.prompts:
            if not (0 <= p.frame_index < n_frames):
                raise PromptError(
                    f"frame_index {p.frame_index} out of range [0, {n_frames}) for the sweep axis"
                )
            for x, y in p.point_coords:
                if not (0 <= x < width and 0 <= y < height):
                    raise PromptError(
                        f"point ({x}, {y}) out of bounds for slice of size (h={height}, w={width})"
                    )
            if p.box is not None:
                x0, y0, x1, y1 = p.box
                if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                    raise PromptError(f"box {p.box.tolist()} out of bounds or malformed")

    def to_record(self) -> dict:
        """Serialize to the same ``{"level", "objects"}`` shape as the on-disk prompt-file format
        (feature 008-level-agnostic-prompts) -- a saved run record's authoring level is visible
        without computing anything.
        """
        objects = []
        for p in self.prompts:
            objects.append(
                {
                    "obj_id": p.obj_id,
                    "frame_index": p.frame_index,
                    "points": [
                        {"xy": [float(x), float(y)], "label": int(lbl)}
                        for (x, y), lbl in zip(p.point_coords, p.point_labels, strict=True)
                    ],
                    "box": None if p.box is None else [float(v) for v in p.box],
                }
            )
        return {"level": self.level, "objects": objects}


def load_prompt_file(path: str | Path) -> PromptSet:
    """Load a prompt file in the documented JSON format (see contracts/cli.md).

    The top-level ``"level"`` key (the pyramid level these coordinates were authored against) is
    required (feature 008-level-agnostic-prompts, FR-007): a file written before that feature
    existed, with no ``"level"`` key, is rejected rather than silently reinterpreted.
    """
    data = json.loads(Path(path).read_text())
    if "level" not in data:
        raise PromptError(
            f'prompt file {path} has no top-level "level" key; this is a pre-feature-008 file '
            "and cannot be safely reused -- re-author it with the level it was authored against"
        )
    level = int(data["level"])
    prompts: list[Prompt] = []
    for obj in data.get("objects", []):
        obj_id = int(obj.get("obj_id", 0))
        by_frame: dict[int, dict] = {}
        for pt in obj.get("points", []):
            f = int(pt["frame"])
            entry = by_frame.setdefault(f, {"coords": [], "labels": []})
            entry["coords"].append(pt["xy"])
            entry["labels"].append(int(pt["label"]))
        box = obj.get("box")
        box_frame = int(box["frame"]) if box else None
        frames = set(by_frame) | ({box_frame} if box_frame is not None else set())
        for f in sorted(frames):
            entry = by_frame.get(f, {"coords": [], "labels": []})
            prompts.append(
                Prompt(
                    frame_index=f,
                    point_coords=entry["coords"] if entry["coords"] else np.empty((0, 2)),
                    point_labels=entry["labels"] if entry["labels"] else np.empty((0,), int),
                    box=np.asarray(box["xyxy"], float) if box and box_frame == f else None,
                    obj_id=obj_id,
                )
            )
    if not prompts:
        raise PromptError("prompt file contains no prompts")
    return PromptSet(prompts=prompts, level=level)
