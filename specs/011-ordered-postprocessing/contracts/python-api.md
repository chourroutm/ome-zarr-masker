# Contract: Python API changes

**Feature**: 011-ordered-postprocessing | **Date**: 2026-10-23

- `PostProcessConfig` is removed from `ome_zarr_masker` and `ome_zarr_masker.config`.
- `OrganMaskPredictor.predict(..., postprocess: str | Sequence[str] | None = None, ...)`: the
  notation of `contracts/postprocess-notation.md`, as one comma-separated string or a list of
  step strings. `None`/`"default"`/`"none"` → no steps (there is no prompt file in the API).
- `InteractiveSession(store_path, level=..., *, prompts_path=None, postprocess=None, ...)`:
  `postprocess` sets the session's steps (as `--postprocess`); with `None`, saved steps from
  `prompts_path` are used if the file exists.
  - `set_postprocess(value)`: validate and replace the session's steps (raises
    `PostProcessError`, keeping the previous steps).
  - `preview(..., postprocess=None)` / `export(...)`: use the session's steps unless `postprocess`
    is passed to `preview`.
  - `save_prompts(path=None) -> Path`: write the prompts and the session's steps (default: the
    session's `prompts_path`).
- New public names in `ome_zarr_masker.postprocess.steps`: `PostProcessError(ValueError)`,
  `PostProcessStep`, `PostProcessSpec`, `parse_steps`.
- C-API-PP-1: The same steps through `predict`, `InteractiveSession.export` and the CLI give
  identical masks (SC-005).
- C-API-PP-2: `save_prompts` then `load_prompt_file` round-trips prompts (at the session level)
  and steps.
