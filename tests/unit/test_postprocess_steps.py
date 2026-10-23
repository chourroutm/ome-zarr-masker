"""Post-processing step notation, specs and radius resolution (feature 011, T002/T015).

Covers contracts/postprocess-notation.md C-PP-4/C-PP-5 and research R1, R2, R5.
"""

from __future__ import annotations

import pytest

from ome_zarr_masker.postprocess.steps import (
    PostProcessError,
    PostProcessSpec,
    PostProcessStep,
    Radius,
    parse_steps,
    resolve_steps,
)

UM = ("micrometer",) * 3

# -- notation (C-PP-4, C-PP-5) ---------------------------------------------------------------


def test_every_op_parses():
    spec = parse_steps("fill,close:3,open:2.5,dilate:1,erode:4,largest,margin:3,invert")
    assert [s.op for s in spec.steps] == [
        "fill", "close", "open", "dilate", "erode", "largest", "margin", "invert"
    ]  # fmt: skip
    assert spec.steps[2].radius == Radius(2.5, None, "2.5")
    assert spec.steps[0].radius is None
    assert spec.source == "cli"


def test_case_and_whitespace_ignored():
    a = parse_steps(" Close : 3 , FILL ,largest ")
    b = parse_steps("close:3,fill,largest")
    assert a.steps == b.steps


def test_list_form_equals_comma_form():
    assert parse_steps(["close:3", "fill"]).steps == parse_steps("close:3,fill").steps


@pytest.mark.parametrize("value", [None, "default", " DEFAULT "])
def test_default_keyword(value):
    spec = parse_steps(value)
    assert spec.steps is None


@pytest.mark.parametrize("value", ["none", "", [], " None "])
def test_no_steps(value):
    spec = parse_steps(value)
    assert spec.steps == ()


@pytest.mark.parametrize(
    "text", ["close:3", "margin:200um", "open:0.15mm", "dilate:2.5", "fill", "invert", "erode:1nm"]
)
def test_str_round_trips(text):
    (step,) = parse_steps(text).steps
    assert str(step) == text
    assert parse_steps(str(step)).steps == (step,)


def test_micro_sign_normalised():
    (a,) = parse_steps("margin:200µm").steps
    (b,) = parse_steps("margin:200UM").steps
    assert a.radius.unit == b.radius.unit == "um"
    assert str(a) == "margin:200um"


@pytest.mark.parametrize(
    ("value", "needle"),
    [
        ("blur:3", "blur"),
        ("close", "close"),
        ("fill:2", "fill:2"),
        ("largest:1", "largest:1"),
        ("invert:1", "invert:1"),
        ("close:0", "close:0"),
        ("close:-1", "close:-1"),
        ("close:abc", "close:abc"),
        ("margin:3furlong", "3furlong"),
        ("default,fill", "default"),
        ("none,fill", "none"),
        ("fill,,close:3", "empty step"),
    ],
)
def test_invalid_steps_name_the_offender(value, needle):
    with pytest.raises(PostProcessError) as exc:
        parse_steps(value)
    assert needle in str(exc.value)


def test_unknown_op_lists_the_accepted_ones():
    with pytest.raises(PostProcessError) as exc:
        parse_steps("blur:3")
    for op in ("fill", "close", "open", "dilate", "erode", "largest", "margin", "invert"):
        assert op in str(exc.value)


def test_source_label():
    assert parse_steps("fill", source="file").source == "file"
    assert parse_steps("default").source == "default"
    assert parse_steps("none").source == "none"


# -- inheritance (research R5) -----------------------------------------------------------------


def test_inherit_uses_saved_steps_for_default():
    saved = parse_steps("close:3,fill").steps
    spec = parse_steps("default").inherit(saved)
    assert spec.steps == saved and spec.source == "prompt_file"


def test_inherit_without_saved_steps_means_none():
    spec = parse_steps("default").inherit(None)
    assert spec.steps == () and spec.source == "default"


@pytest.mark.parametrize("value", ["dilate:1", "none"])
def test_explicit_values_are_not_replaced(value):
    saved = parse_steps("close:3,fill").steps
    spec = parse_steps(value)
    assert spec.inherit(saved) == spec


# -- voxel-radius resolution -------------------------------------------------------------------


def test_resolve_voxel_radii():
    steps = parse_steps("close:3,fill").steps
    close, fill = resolve_steps(steps, (63.0, 63.0, 31.5), UM)
    assert close.radius_voxels == (3.0, 3.0, 3.0)
    assert close.sampling == (1.0, 1.0, 1.0)
    assert close.to_record() == {"op": "close", "radius": "3", "radius_voxels": [3.0, 3.0, 3.0]}
    assert fill.radius_voxels is None and fill.sampling is None
    assert fill.to_record() == {"op": "fill", "radius": None, "radius_voxels": None}


def test_voxel_radii_work_without_units():
    (r,) = resolve_steps(parse_steps("dilate:2").steps, (1.0, 1.0, 1.0), (None, None, None))
    assert r.radius_voxels == (2.0, 2.0, 2.0)


def test_step_is_hashable_and_immutable():
    step = PostProcessStep("fill", None)
    assert {step} == {PostProcessStep("fill", None)}
    with pytest.raises(AttributeError):
        step.op = "close"  # type: ignore[misc]
    assert PostProcessSpec(steps=(), source="none").steps == ()
