# Quickstart: Validate Ordered Post-Processing

Prerequisites: `uv sync --all-extras`. Steps 1–5 run on the login node with the SAM2 stub
(`-m "not real_backend and not slow"`); step 6 runs on a compute node through `salloc`.

1. **Notation and units** (contracts/postprocess-notation.md C-PP-4/5):
   `uv run pytest -q tests/unit/test_postprocess_steps.py` — every accepted form parses and
   round-trips; every rejected form fails with the offending step named; physical radii resolve
   per axis from a level's scale and units (including anisotropic and unit-less axes).
2. **Each step against a reference** (C-PP-1/2/3, SC-001/SC-002):
   `uv run pytest -q tests/unit/test_morphology.py` — voxel-for-voxel equality with explicit
   ellipsoid structures, slab/threads vs whole volume, `close` keeping edge-touching samples, the
   user's sequence `close:3,fill,largest,margin:3` on a synthetic mask with a gap plane, a hole and
   a fragment, and a physical margin at two levels.
3. **CLI** (contracts/cli.md, SC-003): `uv run pytest -q tests/contract/test_cli_mask.py -k postprocess`
   — removed flags are usage errors; `--postprocess` and `--postprocess-file` exclusive; errors exit 1
   before segmentation; `default` inherits prompt-file steps; `none` overrides them; run record
   and log list steps and source.
4. **Prompt files and the interactive session** (US3, SC-007):
   `uv run pytest -q tests/integration/test_postprocess_prompts.py` — a session started with
   `postprocess`, changed with `set_postprocess`, saved with `save_prompts`, then `mask` with that
   prompt file and no `--postprocess` equals the session's export; a session reopened on the file
   shows the saved steps.
5. **Parity and reproducibility** (SC-004/SC-005): same steps via CLI, file, prompt file, API and
   session → identical masks; rerunning with the record's steps → identical mask.
6. **Performance** (SC-006), compute node:
   `salloc -p mit_normal_gpu -A mit_general -c 8 --mem=32G -t 30 srun uv run --no-sync pytest -q -m slow tests/performance/test_postprocess_perf.py`
   — `close:3,fill,largest,margin:3` on 941 × 874 × 874 in < 5 min and < 16 GiB peak RSS.
7. **Regression**: `uv run ruff check src tests`, `uv run ruff format --check src tests`,
   `uv run pytest -q -m "not real_backend and not slow"`, then the slow/real_backend suite via
   `salloc`; the output mask's axes carry the input's units (FR-013).
8. **Real data, outside the test suite** (dandiset 001278): on a GPU node,
   `validation/run_dandi_001278.sh /orcd/scratch/.../ozm-011-check` — masks the small µCT asset
   `sub-Hb1_sample-lefthemi+ICblock+punch1+piece2_uCT.ome.zarr` remotely at level 2 with
   automatically placed prompts and steps saved in the prompt file (`close:100um,fill,largest,
   margin:72um`), and checks inheritance, physical-radius resolution, axis units, and that the
   written mask equals the steps applied to the raw mask. Prints a JSON report; exit 1 on failure.
