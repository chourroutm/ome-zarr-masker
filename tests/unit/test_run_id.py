"""T003: the run identifier is unique and time-sortable (feature 002)."""

from __future__ import annotations

import re

from ome_zarr_masker.input_log import generate_run_id

RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{12}$")


def test_run_id_format_is_timestamp_then_short_uuid():
    rid = generate_run_id()
    assert RUN_ID_RE.match(rid), rid


def test_run_ids_are_unique():
    ids = {generate_run_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_run_ids_are_lexicographically_time_sortable():
    # The fixed-width UTC-timestamp prefix makes ids sort chronologically as plain strings.
    prefixes = [generate_run_id().split("-")[0] for _ in range(5)]
    assert prefixes == sorted(prefixes)
