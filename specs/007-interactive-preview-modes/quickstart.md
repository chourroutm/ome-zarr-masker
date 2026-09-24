# Quickstart: Validate Tiered Interactive Preview Modes

Prerequisites: repo checked out, `pip install -e ".[dev,sam2,interactive]"`. Steps 1 and 5 are
automatable (headless engine and pure helpers, no display); Steps 2-4 need a real display and are
manual, matching this project's existing testing boundary for `InteractiveSession.launch()` (see
plan.md Technical Context).

## 1. Confirm `RunConfig.frame_range` doesn't change existing behavior when unset, and crops
   correctly when set

```python
from organ_masker_lite.config import RunConfig
from organ_masker_lite.engine.pipeline import compute_mask

# unset (None): identical to today -- full axis, byte-for-byte
comp_full = compute_mask(store, prompts, RunConfig(axes=["z"]))

# set: only frames [10, 14] inclusive are actually swept
comp_windowed = compute_mask(store, prompts, RunConfig(axes=["z"], frame_range=(10, 14)))
assert comp_windowed.consensus.shape == comp_full.consensus.shape  # still volume-shaped
```

Expected: `comp_windowed.consensus` differs from `comp_full.consensus` only within frames 10-14;
frames outside that range are all-background (zero) in `comp_windowed` since nothing recomputed
them there — the *caller* (interactive session) is what merges into a pre-existing display, not
`compute_mask` itself. Validates C-PV-12, data-model.md.

## 2. Manual GUI walkthrough — the three modes and their cost tiers

```sh
organ-masker-lite interactive <large_real_input.ome.zarr>
```

- Place a point on the current slice, trigger **single-slice** preview: result appears within
  seconds (target: under 10s, see Step 5 for the automated benchmark); the UI (point placement,
  slice slider) stays responsive the whole time, with a busy indicator visible during the
  computation. Validates FR-003, FR-010, SC-001, SC-005.
- Try triggering another preview shortcut while the single-slice computation is still visibly
  busy: nothing happens until it finishes (no second computation starts). Validates FR-011.
- Trigger **few-slices** preview: result reflects propagation across the fixed ±5-frame window (11
  frames total) around the current slice; move to near frame 0 or the last frame and trigger it
  again to confirm the window clips instead of erroring. Validates FR-004, SC-002.
- Confirm frames *outside* both of the above windows retain whatever the preview layer previously
  showed there (not zeroed out). Validates C-PV-11/research R3.

## 3. Manual GUI walkthrough — whole-volume confirmation

- Trigger **whole-volume** preview: a modal confirmation appears before any computation starts,
  mentioning the time/cost implication. Validates FR-006, C-PV-8.
- Decline it: no computation runs, the existing preview is untouched. Validates FR-006's decline
  clause.
- Accept it: the full-volume result appears (identical to the pre-existing `p` behavior), replacing
  the entire preview layer. Validates FR-005, C-PV-11's whole-volume replace clause.

## 4. Manual GUI walkthrough — export is unaffected by preview mode

- After using single-slice/few-slices preview (not whole-volume), press `e` to export: no
  confirmation dialog appears, and the exported mask reflects the full whole-volume computation
  (not just whatever was last shown in the preview layer). Validates FR-008, C-PV-9.

## 5. Confirm the automated performance benchmark and pure-helper unit tests

```sh
pytest tests/performance/test_frame_range_perf.py -m real_backend -q
pytest tests/unit/test_interactive_preview_state.py -q
```

Expected: the performance test confirms single-slice completes under 10s and few-slices timing is
comparable across very different volume depths (SC-001/SC-002, C-PV-13/14); the unit test confirms
`_PreviewBusyGuard`'s acquire/release semantics and `_clip_window`'s boundary clipping, both without
a display (research R4).
