"""Unit tests for interactive.py's pure, display-independent preview-state helpers (research R4).

Fast and GPU-free/display-free: these exercise plain Python/logic, not napari's GUI.
"""

from __future__ import annotations

from ome_zarr_masker.interactive import _clip_window, _PreviewBusyGuard


def test_try_start_succeeds_when_idle_and_marks_busy():
    guard = _PreviewBusyGuard()
    assert guard.try_start() is True
    assert guard.busy is True


def test_try_start_is_a_noop_while_already_busy():
    guard = _PreviewBusyGuard()
    assert guard.try_start() is True
    assert guard.try_start() is False  # second trigger while busy: no-op (FR-011)
    assert guard.busy is True


def test_finish_clears_busy_state_allowing_a_new_start():
    guard = _PreviewBusyGuard()
    guard.try_start()
    guard.finish()
    assert guard.busy is False
    assert guard.try_start() is True


def test_clip_window_centers_on_current_frame_away_from_boundaries():
    assert _clip_window(50, half_width=5, n_frames=100) == (45, 55)


def test_clip_window_clips_at_the_start_boundary():
    assert _clip_window(2, half_width=5, n_frames=100) == (0, 7)


def test_clip_window_clips_at_the_end_boundary():
    assert _clip_window(97, half_width=5, n_frames=100) == (92, 99)


def test_clip_window_handles_a_volume_smaller_than_the_window():
    assert _clip_window(3, half_width=5, n_frames=6) == (0, 5)
