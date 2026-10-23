"""CLI contract tests for `ome-zarr-masker mask` (T029, contracts/cli.md C-CLI-1/4/6).

SAM2 is the only backend; there is no `--backend` flag. Tests that only exercise argument parsing
or fail during pre-flight validation (before segmentation runs) need no real backend. Tests that
run the pipeline to completion are marked ``real_backend`` and require a real, GPU-powered SAM2
install to actually execute (skipped otherwise).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ome_zarr_masker.cli import main
from ome_zarr_masker.io.reader import OmeZarrReader

from ..conftest import sam2_available, write_ome_zarr

_HAVE_SAM2 = sam2_available()
requires_sam2 = pytest.mark.skipif(not _HAVE_SAM2, reason="sam2 backend not constructable")


def _write_prompts(path: Path, *, points=None, box=None, level=0) -> Path:
    obj: dict = {"obj_id": 0}
    if points is not None:
        obj["points"] = points
    if box is not None:
        obj["box"] = box
    path.write_text(json.dumps({"level": level, "objects": [obj]}))
    return path


@pytest.fixture
def valid_input(tmp_path):
    vol = np.zeros((8, 16, 16), np.uint8)
    vol[2:6, 4:12, 4:12] = 200
    return write_ome_zarr(tmp_path / "in.ome.zarr", vol)


def _single_point_prompts(tmp_path) -> Path:
    return _write_prompts(tmp_path / "p.json", points=[{"frame": 4, "xy": [8, 8], "label": 1}])


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["mask", "--help"])
    assert exc.value.code == 0


def test_usage_error_exits_two():
    # missing required positional/option -> argparse usage error
    with pytest.raises(SystemExit) as exc:
        main(["mask"])
    assert exc.value.code == 2


def test_postprocess_documented_in_help(capsys):
    """Feature 011: `mask --help` describes --postprocess, its steps and keywords."""
    with pytest.raises(SystemExit) as exc:
        main(["mask", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for word in ("--postprocess", "close", "largest", "margin", "invert", "default", "none"):
        assert word in out


@pytest.mark.parametrize(
    "removed",
    [["--invert"], ["--fill-holes"], ["--no-fill-holes"], ["--dilate", "1"], ["--erode", "1"]],
)
def test_removed_postprocess_options_point_to_postprocess(removed, capsys):
    """Feature 011, FR-010: the old options are usage errors naming --postprocess."""
    with pytest.raises(SystemExit) as exc:
        main(["mask", "in.ome.zarr", "out.ome.zarr", "--prompts", "p.json", *removed])
    assert exc.value.code == 2
    assert "--postprocess" in capsys.readouterr().err


def test_backend_flag_rejected(valid_input, tmp_path):
    """C-CLI-6: --backend no longer exists; argparse rejects it as unrecognized."""
    prompts = _single_point_prompts(tmp_path)
    out = tmp_path / "out.ome.zarr"
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "mask",
                str(valid_input),
                str(out),
                "--prompts",
                str(prompts),
                "--backend",
                "sam3",
                "--level",
                "0",
            ]
        )
    assert exc.value.code == 2
    assert not out.exists()


@pytest.mark.real_backend
@requires_sam2
def test_success_writes_valid_output_same_levels(valid_input, tmp_path):
    prompts = _single_point_prompts(tmp_path)
    out = tmp_path / "out.ome.zarr"
    code = main(
        [
            "mask",
            str(valid_input),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "0",
        ]
    )
    assert code == 0
    assert OmeZarrReader(out).n_levels == OmeZarrReader(valid_input).n_levels


def test_invalid_input_store_exits_one_no_output(tmp_path):
    prompts = _single_point_prompts(tmp_path)
    out = tmp_path / "out.ome.zarr"
    code = main(
        [
            "mask",
            str(tmp_path / "missing.ome.zarr"),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "0",
        ]
    )
    assert code == 1
    assert not out.exists()


def test_missing_level_exits_one_no_output(valid_input, tmp_path):
    prompts = _single_point_prompts(tmp_path)
    out = tmp_path / "out.ome.zarr"
    code = main(
        [
            "mask",
            str(valid_input),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "99",
        ]
    )
    assert code == 1
    assert not out.exists()


def test_empty_prompts_exits_one(valid_input, tmp_path):
    prompts = _write_prompts(tmp_path / "empty.json", points=[])
    out = tmp_path / "out.ome.zarr"
    code = main(
        [
            "mask",
            str(valid_input),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "0",
        ]
    )
    assert code == 1
    assert not out.exists()


def test_out_of_bounds_prompt_exits_one(valid_input, tmp_path):
    prompts = _write_prompts(
        tmp_path / "oob.json", points=[{"frame": 4, "xy": [999, 999], "label": 1}]
    )
    out = tmp_path / "out.ome.zarr"
    code = main(
        [
            "mask",
            str(valid_input),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "0",
        ]
    )
    assert code == 1
    assert not out.exists()


@pytest.mark.real_backend
@requires_sam2
def test_existing_output_without_overwrite_exits_one(valid_input, tmp_path):
    prompts = _single_point_prompts(tmp_path)
    out = tmp_path / "out.ome.zarr"
    out.mkdir()
    (out / "sentinel.txt").write_text("keep me")
    code = main(
        [
            "mask",
            str(valid_input),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "0",
        ]
    )
    assert code == 1
    # existing content untouched
    assert (out / "sentinel.txt").read_text() == "keep me"


@pytest.mark.real_backend
@requires_sam2
def test_overwrite_flag_allows_replacement(valid_input, tmp_path):
    prompts = _single_point_prompts(tmp_path)
    out = tmp_path / "out.ome.zarr"
    out.mkdir()
    (out / "stale.txt").write_text("old")
    code = main(
        [
            "mask",
            str(valid_input),
            str(out),
            "--prompts",
            str(prompts),
            "--level",
            "0",
            "--overwrite",
        ]
    )
    assert code == 0
    assert OmeZarrReader(out).n_levels == OmeZarrReader(valid_input).n_levels


# -- feature 009: --workers (FR-011, C-W-CLI-2/3) -----------------------------------------------


def test_workers_zero_is_usage_error_and_writes_nothing(valid_input, tmp_path, capsys):
    out = tmp_path / "out.ome.zarr"
    argv = ["mask", str(valid_input), str(out), "--prompts", str(_single_point_prompts(tmp_path))]
    with pytest.raises(SystemExit) as exc:
        main([*argv, "--workers", "0"])
    assert exc.value.code == 2
    assert "--workers" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.real_backend
@requires_sam2
def test_workers_does_not_change_output(valid_input, tmp_path):
    import json

    prompts = _single_point_prompts(tmp_path)
    outs = []
    for name, extra in (("auto", []), ("two", ["--workers", "2"])):
        out = tmp_path / f"{name}.ome.zarr"
        code = main(
            ["mask", str(valid_input), str(out), "--prompts", str(prompts), "--level", "0", *extra]
        )
        assert code == 0
        outs.append(out)
    a, b = (OmeZarrReader(o) for o in outs)
    for i in range(a.n_levels):
        assert np.array_equal(a.read_level(i), b.read_level(i))
    ra, rb = (json.loads((o / "run_record.json").read_text()) for o in outs)
    ra.pop("run_id")
    rb.pop("run_id")
    assert ra == rb


# -- remote stores (feature 010, T010: C-R-CLI-1/7/8, C-LOC-2/3, FR-011) ---------------------


@pytest.fixture
def stub_sam2(monkeypatch):
    """Replace SAM2 with the deterministic stub: these cases test I/O, not segmentation."""
    from ome_zarr_masker.engine import pipeline

    from ..conftest import StubBackend

    monkeypatch.setattr(pipeline, "Sam2Backend", lambda config=None: StubBackend())


def _log_text(tmp_path) -> str:
    return "\n".join(p.read_text() for p in (tmp_path / "_logs").rglob("*") if p.is_file())


def test_remote_http_input_local_output(
    valid_input, tmp_path, http_store_server, stub_sam2, capsys
):
    import shutil

    from ..conftest import assert_ome_zarr_models_valid

    shutil.copytree(valid_input, http_store_server.root / "in.ome.zarr")
    url = http_store_server.url("in.ome.zarr")
    out = tmp_path / "out.ome.zarr"
    prompts = _single_point_prompts(tmp_path)
    code = main(["mask", url, str(out), "--prompts", str(prompts), "--level", "0"])
    assert code == 0, capsys.readouterr().err
    assert capsys.readouterr().out.strip() == str(out)
    assert_ome_zarr_models_valid(out)
    assert json.loads((out / "run_record.json").read_text())["input"] == url
    assert url in _log_text(tmp_path)


@pytest.mark.parametrize(
    ("url", "secret"),
    [("ftp://host/in.ome.zarr", None), ("https://u:s3cr3t@example.org/in.ome.zarr", "s3cr3t")],
)
def test_bad_remote_input_exits_one_cleanly(tmp_path, capsys, url, secret):
    out = tmp_path / "out.ome.zarr"
    prompts = _single_point_prompts(tmp_path)
    code = main(["mask", url, str(out), "--prompts", str(prompts)])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1 and captured.err.startswith("error: ")
    assert not out.exists()
    if secret is not None:
        assert secret not in captured.err
        assert secret not in _log_text(tmp_path)


def test_missing_remote_input_exits_one(tmp_path, http_store_server, capsys):
    out = tmp_path / "out.ome.zarr"
    prompts = _single_point_prompts(tmp_path)
    url = http_store_server.url("nope.ome.zarr")
    code = main(["mask", url, str(out), "--prompts", str(prompts)])
    captured = capsys.readouterr()
    assert code == 1 and captured.out == ""
    assert "not found" in captured.err and url in captured.err
    assert not out.exists()


# -- ordered post-processing (feature 011, T007: contracts/cli.md C-CLI-PP-1..3) --------------


def _mask_cli(valid_input, out, prompts, *extra):
    return main(
        ["mask", str(valid_input), str(out), "--prompts", str(prompts), "--level", "0", *extra]
    )


@pytest.mark.parametrize(("value", "needle"), [("blur:3", "blur:3"), ("fill:2", "fill:2")])
def test_invalid_postprocess_exits_one_before_segmentation(
    valid_input, tmp_path, monkeypatch, capsys, value, needle
):
    from ome_zarr_masker.engine import pipeline

    calls = []
    monkeypatch.setattr(pipeline, "Sam2Backend", lambda config=None: calls.append(1))
    out = tmp_path / "out.ome.zarr"
    code = _mask_cli(valid_input, out, _single_point_prompts(tmp_path), "--postprocess", value)
    captured = capsys.readouterr()
    assert code == 1 and calls == [] and captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert needle in captured.err and "--postprocess" in captured.err
    assert not out.exists()


def test_postprocess_steps_applied_in_order_and_recorded(valid_input, tmp_path, stub_sam2):
    from ome_zarr_masker.postprocess.morphology import apply_steps
    from ome_zarr_masker.postprocess.steps import parse_steps, resolve_steps

    prompts = _single_point_prompts(tmp_path)
    raw_out, out = tmp_path / "raw.ome.zarr", tmp_path / "pp.ome.zarr"
    assert _mask_cli(valid_input, raw_out, prompts, "--postprocess", "none") == 0
    assert _mask_cli(valid_input, out, prompts, "--postprocess", "close:1,fill") == 0

    raw = OmeZarrReader(raw_out).read_level(0).astype(bool)
    steps = resolve_steps(parse_steps("close:1,fill").steps, (1.0,) * 3, (None,) * 3)
    expected = apply_steps(raw, steps).astype(np.uint8)
    np.testing.assert_array_equal(OmeZarrReader(out).read_level(0), expected)

    record = json.loads((out / "run_record.json").read_text())["config"]["postprocess"]
    assert record == {
        "source": "cli",
        "steps": [
            {"op": "close", "radius": "1", "radius_voxels": [1.0, 1.0, 1.0]},
            {"op": "fill", "radius": None, "radius_voxels": None},
        ],
    }
    assert "close:1" in _log_text(tmp_path)


def test_no_postprocess_option_means_no_steps(valid_input, tmp_path, stub_sam2):
    """FR-004: the default is `default`; with no saved steps nothing (not even fill) is applied."""
    prompts = _single_point_prompts(tmp_path)
    a, b = tmp_path / "a.ome.zarr", tmp_path / "b.ome.zarr"
    assert _mask_cli(valid_input, a, prompts) == 0
    assert _mask_cli(valid_input, b, prompts, "--postprocess", "none") == 0
    np.testing.assert_array_equal(OmeZarrReader(a).read_level(0), OmeZarrReader(b).read_level(0))
    record = json.loads((a / "run_record.json").read_text())["config"]["postprocess"]
    assert record == {"source": "default", "steps": []}


# -- steps saved in the prompt file (feature 011 US3, T021) ------------------------------------


def _prompts_with_steps(tmp_path, steps) -> Path:
    path = tmp_path / "saved.json"
    obj = {"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}]}
    path.write_text(json.dumps({"level": 0, "objects": [obj], "postprocess": steps}))
    return path


def _pp_record(out) -> dict:
    return json.loads((out / "run_record.json").read_text())["config"]["postprocess"]


def test_saved_steps_are_inherited_overridden_or_disabled(valid_input, tmp_path, stub_sam2):
    prompts = _prompts_with_steps(tmp_path, ["close:1", "fill"])
    inherited, none, override = (tmp_path / f"{n}.ome.zarr" for n in ("i", "n", "o"))
    assert _mask_cli(valid_input, inherited, prompts) == 0
    assert _mask_cli(valid_input, none, prompts, "--postprocess", "none") == 0
    assert _mask_cli(valid_input, override, prompts, "--postprocess", "dilate:1") == 0

    rec = _pp_record(inherited)
    assert rec["source"] == "prompt_file" and [s["op"] for s in rec["steps"]] == ["close", "fill"]
    assert _pp_record(none) == {"source": "none", "steps": []}
    rec = _pp_record(override)
    assert rec["source"] == "cli" and [s["op"] for s in rec["steps"]] == ["dilate"]
    dilated = OmeZarrReader(override).read_level(0)
    assert dilated.sum() > OmeZarrReader(none).read_level(0).sum()


def test_invalid_saved_steps_fail_before_segmentation(valid_input, tmp_path, monkeypatch, capsys):
    from ome_zarr_masker.engine import pipeline

    calls = []
    monkeypatch.setattr(pipeline, "Sam2Backend", lambda config=None: calls.append(1))
    prompts = _prompts_with_steps(tmp_path, ["blur:3"])
    out = tmp_path / "out.ome.zarr"
    code = _mask_cli(valid_input, out, prompts)
    err = capsys.readouterr().err
    assert code == 1 and calls == [] and not out.exists()
    assert str(prompts) in err and "blur:3" in err
