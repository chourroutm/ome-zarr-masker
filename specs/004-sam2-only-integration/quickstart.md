# Quickstart: Validate SAM2-Only Integration

Prerequisites: repo checked out, `pip install -e ".[dev,sam2]"` (no `sam3` extra exists after this
feature). Steps 4-6 require a GPU with SAM2 weights available (e.g., this project's HPC GPU nodes);
run them there. Run all commands from the repo root.

## 1. Confirm SAM3 is fully gone

```sh
grep -rli sam3 src/ tests/ README.md pyproject.toml
```

Expected: no output (empty). Validates SC-002.

## 2. Confirm the backend abstraction is fully gone

```sh
grep -rn "VideoSegmenterBackend\|register_backend\|get_backend\|BackendError\|backends\." src/ tests/
ls src/ome_zarr_masker/backends 2>&1   # expect: No such file or directory
```

Expected: no matches for the first command; the `backends/` directory no longer exists. Validates
SC-002/SC-003 (5 files collapsed into `src/ome_zarr_masker/sam2.py`).

## 3. Confirm the old `--backend` flag is rejected, not silently accepted

```sh
ome-zarr-masker mask <input.ome.zarr> <out.ome.zarr> --prompts <prompts.json> --backend sam3
echo "exit: $?"
```

Expected: non-zero exit, `argparse`'s standard "unrecognized arguments: --backend" message (C-CLI-6)
— not a custom "unknown backend" message, since the flag no longer exists at all.

```python
from ome_zarr_masker import OrganMaskPredictor
OrganMaskPredictor(backend="sam3")  # expect: TypeError: unexpected keyword argument 'backend'
```

## 4. Confirm the test suite exercises real SAM2 (no CPU-only stand-in remains)

```sh
pytest -m real_backend -q
```

Expected: on a machine with GPU + SAM2 weights, these tests run the real SAM2 predictor end-to-end
and pass (SC-006). On a machine without them, each skips individually with a clear reason (FR-010)
— the run as a whole still completes, it does not hard-crash.

```sh
grep -rn "StubBackend\|stub_backend\|register_backend" tests/
```

Expected: no matches — the deterministic stand-in is gone.

## 5. Confirm a real SAM2 run still produces the same output as before the refactor (FR-009, SC-004)

```sh
ome-zarr-masker mask <input.ome.zarr> <out_before.ome.zarr> --prompts <prompts.json>
# (after applying this feature's changes, same command — there is no --backend flag anymore)
ome-zarr-masker mask <input.ome.zarr> <out_after.ome.zarr> --prompts <prompts.json>
```

Expected: `out_before.ome.zarr` and `out_after.ome.zarr` are pixel-identical.

## 6. Confirm the README documents only SAM2, with no `--backend` flag

Read through `README.md` end-to-end. Expected: no "SAM3" section, no `HF_TOKEN`/gated-weights/BPE
vocab instructions, no `--backend` flag anywhere, no `pip install -e ".[sam3]"` line (SC-005).

See [data-model.md](./data-model.md) for the exhaustive file inventory these checks are derived
from, and [contracts/](./contracts/) for the precise CLI/API contract deltas.
