# Quickstart: Validate Interactive Prompt Layers

Prerequisites: repo checked out, `pip install -e ".[dev,sam2,interactive]"`. Steps 1-2 need a
GPU with SAM2 weights (headless core only, no display needed); Steps 3-4 need an actual display
and are manual, since `launch()` has no automated coverage in this project (matching its existing,
unchanged testing boundary — see plan.md Technical Context).

## 1. Confirm points+box on the same frame merge into one prompt (no silent drop)

```python
from ome_zarr_masker.interactive import InteractiveSession

session = InteractiveSession("<input.ome.zarr>", level=0)
session.add_positive_point(frame_index=4, x=8, y=8)
session.add_box(frame_index=4, box=[2, 2, 20, 20])
result = session.preview(axes=["z"])
```

Expected: no exception, and the resulting mask reflects both the point and the box prompt on frame
4 (not just whichever was added last). Validates research R2 / C-UI-13/14.

## 2. Confirm interactive/CLI parity (SC-004)

```python
import numpy as np

# same point + box via the interactive headless core
session = InteractiveSession("<input.ome.zarr>", level=0)
session.add_positive_point(frame_index=4, x=8, y=8)
session.add_box(frame_index=4, box=[2, 2, 20, 20])
interactive_mask = session.preview(axes=["z"]).array
```

```sh
# same point + box via an equivalent CLI prompt file
cat > prompts.json <<'EOF'
{"objects": [{"obj_id": 0, "points": [{"frame": 4, "xy": [8, 8], "label": 1}],
              "box": {"frame": 4, "xyxy": [2, 2, 20, 20]}}]}
EOF
ome-zarr-masker mask <input.ome.zarr> cli_out.ome.zarr --prompts prompts.json --level 0 --axes z
```

```python
from ome_zarr_masker.io.reader import OmeZarrReader
cli_mask = OmeZarrReader("cli_out.ome.zarr").read_level(0)
assert np.array_equal(interactive_mask.astype("uint8"), cli_mask)
```

Expected: masks are identical. Validates C-UI-15/SC-004.

## 3. Manual GUI walkthrough — layers and appearance (C-UI-1 through C-UI-6)

```sh
ome-zarr-masker interactive <input.ome.zarr>
```

- Confirm the layers list shows `volume`, `positive-points`, `negative-points`, `positive-box`
  (no single "prompts" layer).
- Click to place a point: it must appear in `positive-points` as a lime cross, size 7, no border.
- Select it, press `n`: it must disappear from `positive-points` and reappear in
  `negative-points` as a red disc, size 6, no border.
- Draw a rectangle in `positive-box`: it must render translucent, no depth shading relative to the
  volume, opacity 100%, a 1px lime edge, and a fully transparent interior.
- Try the ellipse/line/polygon/path tools on `positive-box`: none of the resulting shapes should
  persist in that layer.

## 4. Manual GUI walkthrough — selection continuity and auto-clear (C-UI-7 through C-UI-12)

- Place a point in `positive-points` (auto-selected), press `n` (moves to `negative-points`,
  stays selected there), press `y` immediately with no reselection: it must flip straight back to
  `positive-points`. Validates FR-004b.
- Select a point in `positive-points`, switch to interact with `negative-points` and place a new
  point there, then press `n`: only the newly placed point should flip — the earlier `positive-
  points` selection must not have carried over. Validates FR-004a.
