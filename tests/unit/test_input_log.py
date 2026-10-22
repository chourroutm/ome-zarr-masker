"""T004: the per-invocation log lifecycle (feature 002).

Writes a per-invocation file with header + outcome, is best-effort on an unwritable directory
(warns to stderr, raises nothing), and writes nothing to stdout.
"""

from __future__ import annotations

import pytest

from ome_zarr_masker.config import LogConfig
from ome_zarr_masker.input_log import log_invocation


def test_writes_header_and_success_outcome(tmp_path):
    cfg = LogConfig(log_dir=tmp_path / "logs")
    with log_invocation("ome-zarr-masker mask in out", cfg, arguments={"backend": "stub"}) as log:
        run_id = log.run_id
        path = log.path
    text = path.read_text()
    assert f"run_id: {run_id}" in text
    assert "command: ome-zarr-masker mask in out" in text
    assert "backend: stub" in text
    assert "outcome: succeeded" in text


def test_marks_failed_outcome_explicitly(tmp_path):
    cfg = LogConfig(log_dir=tmp_path / "logs")
    with log_invocation("cmd", cfg) as log:
        log.mark_failed("boom")
        path = log.path
    assert "outcome: failed - boom" in path.read_text()


def test_marks_failed_and_reraises_on_exception(tmp_path):
    cfg = LogConfig(log_dir=tmp_path / "logs")
    holder = {}
    with pytest.raises(ValueError):
        with log_invocation("cmd", cfg) as log:
            holder["path"] = log.path
            raise ValueError("kaboom")
    text = holder["path"].read_text()
    assert "outcome: failed" in text
    assert "ValueError: kaboom" in text


def test_best_effort_on_unwritable_dir_warns_to_stderr(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    cfg = LogConfig(log_dir=blocker / "sub")  # mkdir under a file fails
    with log_invocation("cmd", cfg) as log:
        assert log.path is None  # never created
    captured = capsys.readouterr()
    assert captured.out == ""  # nothing on stdout
    assert "input logging disabled" in captured.err


def test_writes_nothing_to_stdout(tmp_path, capsys):
    cfg = LogConfig(log_dir=tmp_path / "logs")
    with log_invocation("cmd", cfg, arguments={"a": 1}) as log:
        log.record_config({"backend": "stub", "level": 0})
    assert capsys.readouterr().out == ""
