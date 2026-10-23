"""Ordered post-processing steps: notation, specs and radius resolution (feature 011).

One notation is shared by ``--postprocess``, post-processing files, the steps saved in prompt files,
the Python API and the interactive panel (contracts/postprocess-notation.md): a step is ``op`` or
``op:R`` and a sequence is a comma-separated string or a list of step strings, e.g.
``close:3,fill,largest,margin:200um,invert``. The keywords ``default`` (inherit the prompt file's
saved steps, else none) and ``none`` (no steps) stand alone.

Everything here runs before segmentation, so a bad step fails fast (FR-008). A radius without a
unit is in run-level voxels; :func:`resolve_steps` turns every radius into a per-axis voxel radius
for the run level (research R1, R2, R5).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

#: Steps that take a radius, and steps that must not.
RADIUS_OPS = ("close", "open", "dilate", "erode", "margin")
PLAIN_OPS = ("fill", "largest", "invert")
OPS = ("fill", "close", "open", "dilate", "erode", "largest", "margin", "invert")
KEYWORDS = ("default", "none")

#: Units accepted in a radius, in metres.
RADIUS_UNITS = {"nm": 1e-9, "um": 1e-6, "mm": 1e-3, "cm": 1e-2, "m": 1.0}

#: OME-Zarr 0.5 length units for axes, in metres.
AXIS_UNITS = {
    "yoctometer": 1e-24, "zeptometer": 1e-21, "attometer": 1e-18, "femtometer": 1e-15,
    "picometer": 1e-12, "angstrom": 1e-10, "nanometer": 1e-9, "micrometer": 1e-6,
    "millimeter": 1e-3, "centimeter": 1e-2, "decimeter": 1e-1, "meter": 1.0,
    "hectometer": 1e2, "kilometer": 1e3, "megameter": 1e6, "gigameter": 1e9,
    "terameter": 1e12, "petameter": 1e15, "exameter": 1e18, "zettameter": 1e21,
    "yottameter": 1e24, "inch": 0.0254, "foot": 0.3048, "yard": 0.9144, "mile": 1609.344,
    "parsec": 3.0856775814913673e16,
}  # fmt: skip

_RADIUS = re.compile(r"^(?P<value>[0-9]*\.?[0-9]+(?:e[+-]?[0-9]+)?)\s*(?P<unit>[a-zµ]*)$")


class PostProcessError(ValueError):
    """A post-processing step, radius or sequence is invalid (raised before segmentation)."""


@dataclass(frozen=True)
class Radius:
    """A positive radius: run-level voxels (``unit is None``) or a physical length."""

    value: float
    unit: str | None
    text: str

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class PostProcessStep:
    """One operation of a sequence, with its radius when it takes one."""

    op: str
    radius: Radius | None = None

    def __str__(self) -> str:
        return self.op if self.radius is None else f"{self.op}:{self.radius}"


@dataclass(frozen=True)
class PostProcessSpec:
    """What was asked for: ``steps is None`` means ``default`` (inherit), ``()`` means none."""

    steps: tuple[PostProcessStep, ...] | None
    source: str

    def inherit(self, saved: tuple[PostProcessStep, ...] | None) -> PostProcessSpec:
        """Resolve ``default`` against a prompt file's saved steps (research R5)."""
        if self.steps is not None:
            return self
        if saved is None:
            return PostProcessSpec(steps=(), source="default")
        return PostProcessSpec(steps=tuple(saved), source="prompt_file")

    def text(self) -> str:
        """The sequence in the shared notation (``default`` / ``none`` for the keywords)."""
        if self.steps is None:
            return "default"
        return ",".join(map(str, self.steps)) if self.steps else "none"


@dataclass(frozen=True)
class ResolvedStep:
    """A step with its radius in voxels along each axis of the run level."""

    step: PostProcessStep
    radius_voxels: tuple[float, ...] | None = None
    #: Voxel size along each axis, in the radius's unit (all 1 for a voxel radius).
    sampling: tuple[float, ...] | None = None

    @property
    def op(self) -> str:
        return self.step.op

    def to_record(self) -> dict:
        """The step as recorded in run records and input logs (FR-012, research R7)."""
        return {
            "op": self.step.op,
            "radius": None if self.step.radius is None else self.step.radius.text,
            "radius_voxels": None if self.radius_voxels is None else list(self.radius_voxels),
        }


def _accepted() -> str:
    return (
        f"steps: {', '.join(OPS)} (radius R required for {', '.join(RADIUS_OPS)}), "
        f"or {' / '.join(KEYWORDS)} alone; R is a number of voxels or a length in "
        f"{', '.join(('nm', 'um', 'mm', 'cm', 'm'))}"
    )


def _parse_radius(text: str, step_text: str) -> Radius:
    m = _RADIUS.match(text.strip().lower())
    if m is None:
        raise PostProcessError(f"invalid radius in '{step_text}'; {_accepted()}")
    value = float(m.group("value"))
    unit = m.group("unit").replace("µ", "u") or None
    if unit is not None and unit not in RADIUS_UNITS:
        raise PostProcessError(
            f"unknown unit in '{step_text}'; accepted units: nm, um (µm), mm, cm, m"
        )
    if not value > 0 or not math.isfinite(value):
        raise PostProcessError(f"radius must be positive in '{step_text}'")
    number = m.group("value")
    return Radius(value, unit, number + (unit or ""))


def _parse_step(text: str) -> PostProcessStep:
    raw = text.strip()
    if not raw:
        raise PostProcessError(f"empty step in the sequence; {_accepted()}")
    op, sep, radius = (part.strip() for part in raw.partition(":"))
    op = op.lower()
    if op not in OPS:
        raise PostProcessError(f"unknown step '{raw}'; {_accepted()}")
    if op in PLAIN_OPS:
        if sep:
            raise PostProcessError(f"'{raw}': {op} takes no radius")
        return PostProcessStep(op)
    if not sep or not radius:
        raise PostProcessError(f"'{raw}': {op} needs a radius, e.g. {op}:3 or {op}:200um")
    return PostProcessStep(op, _parse_radius(radius, raw))


def parse_steps(value: str | Sequence[str] | None, source: str = "cli") -> PostProcessSpec:
    """Parse a sequence in the shared notation (a comma-separated string or a list of steps).

    ``None`` and ``default`` give ``steps=None`` (inherit); ``none``, ``""`` and ``[]`` give no
    steps. ``source`` labels where the sequence came from (``default``/``none`` are labelled by
    the keyword). Raises :class:`PostProcessError` naming the offending step.
    """
    if value is None:
        return PostProcessSpec(steps=None, source="default")
    parts = value.split(",") if isinstance(value, str) else [str(v) for v in value]
    if isinstance(value, str) and not value.strip():
        parts = []
    lowered = [p.strip().lower() for p in parts]
    for keyword in KEYWORDS:
        if keyword in lowered:
            if len(lowered) > 1:
                raise PostProcessError(
                    f"'{keyword}' must be used alone, not with other steps: '{','.join(parts)}'"
                )
            steps = None if keyword == "default" else ()
            return PostProcessSpec(steps=steps, source=keyword)
    if not parts:
        return PostProcessSpec(steps=(), source="none")
    return PostProcessSpec(steps=tuple(_parse_step(p) for p in parts), source=source)


def load_postprocess_file(path: str | Path) -> PostProcessSpec:
    """Read a post-processing file: a JSON object with a ``"postprocess"`` list (research R6).

    Other keys are ignored, so a prompt file with saved steps can be used too. Keywords are not
    allowed in files (an empty list means no steps).
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise PostProcessError(f"cannot read post-processing file {path}: {exc}") from exc
    if not isinstance(data, dict) or "postprocess" not in data:
        raise PostProcessError(
            f'post-processing file {path} needs a "postprocess" list, e.g. '
            '{"postprocess": ["close:3", "fill"]}'
        )
    return steps_from_json(data["postprocess"], str(path), source="file")


def steps_from_json(value, where: str, source: str) -> PostProcessSpec:
    """Steps stored in a JSON file (post-processing or prompt file); errors name ``where``."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise PostProcessError(f'{where}: "postprocess" must be a list of step strings')
    if any(v.strip().lower() in KEYWORDS for v in value):
        raise PostProcessError(
            f'{where}: "default" and "none" are not allowed in a file; use [] for no steps'
        )
    try:
        spec = parse_steps(value, source=source)
    except PostProcessError as exc:
        raise PostProcessError(f"{where}: {exc}") from exc
    return replace(spec, source=source)


def resolve_steps(
    steps: Sequence[PostProcessStep],
    scale: Sequence[float],
    axis_units: Sequence[str | None],
) -> tuple[ResolvedStep, ...]:
    """Each step's radius in run-level voxels per axis (research R2).

    ``scale`` is the run level's voxel size per axis and ``axis_units`` the axes' OME-Zarr units.
    """
    ndim = len(scale)
    resolved = []
    for step in steps:
        if step.radius is None:
            resolved.append(ResolvedStep(step))
            continue
        if step.radius.unit is None:
            r = float(step.radius.value)
            resolved.append(ResolvedStep(step, (r,) * ndim, (1.0,) * ndim))
            continue
        resolved.append(_resolve_physical(step, scale, axis_units))
    return tuple(resolved)


def _resolve_physical(
    step: PostProcessStep, scale: Sequence[float], axis_units: Sequence[str | None]
) -> ResolvedStep:
    """A physical radius in voxels along each axis: ``R / voxel size`` (FR-006)."""
    radius = step.radius
    if any(u is None for u in axis_units):
        raise PostProcessError(
            f"'{step}': this store's axes declare no unit, so a physical radius can't be "
            f"converted; give the radius in voxels instead (e.g. {step.op}:3)"
        )
    bad = [u for u in axis_units if u not in AXIS_UNITS]
    if bad:
        raise PostProcessError(
            f"'{step}': axis unit {bad[0]!r} is not a length; give the radius in voxels instead"
        )
    per_unit = RADIUS_UNITS[radius.unit]
    # each axis's voxel size, expressed in the radius's unit
    sampling = tuple(
        float(s) * AXIS_UNITS[u] / per_unit for s, u in zip(scale, axis_units, strict=True)
    )
    radius_voxels = tuple(radius.value / s for s in sampling)
    if all(r < 1 for r in radius_voxels):
        sizes = ", ".join(f"{s:.4g}" for s in sampling)
        raise PostProcessError(
            f"'{step}' is smaller than one voxel along every axis at this level (voxel size "
            f"{sizes} {radius.unit}); use a larger radius or a finer level"
        )
    return ResolvedStep(step, radius_voxels, sampling)


__all__ = [
    "OPS",
    "PostProcessError",
    "PostProcessSpec",
    "PostProcessStep",
    "Radius",
    "ResolvedStep",
    "load_postprocess_file",
    "parse_steps",
    "resolve_steps",
    "steps_from_json",
]
