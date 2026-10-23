---

description: "Task list for feature 011: ordered post-processing pipeline"
---

# Tasks: Ordered Post-Processing Pipeline

**Input**: Design documents from `/specs/011-ordered-postprocessing/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R9), data-model.md, contracts/
(postprocess-notation.md, cli.md, python-api.md), quickstart.md

**Tests**: Required (Constitution II). Write each test task first and confirm it fails before the
matching implementation task. On the login node run only `-m "not real_backend and not slow"`;
`slow` and `real_backend` tests run on a compute node through `salloc` (as in feature 010).

**Organization**: US1 (P1) ordered steps on the command line, US2 (P2) physical radii, US3 (P3)
interactive panel and steps saved with prompts, US4 (P4) post-processing files, parity and
reproducibility.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: User story the task belongs to (US1–US4)

## Path Conventions

Single project: package `src/ome_zarr_masker/`, tests under `tests/`. Commands run from the repo
root with `uv run --no-sync`.

---

## Phase 1: Setup

- [X] T001 Confirm the starting point: `uv run --no-sync pytest -q -m "not real_backend and not slow"` passes on the login node (feature 010 end state: 255 passed, 4 skipped) and record the GPU baseline from feature 010's quickstart validation (48 passed for `-m "slow or real_backend"`); list every use of the old options to replace: `grep -rn -- '--invert\|--fill-holes\|--dilate\|--erode\|PostProcessConfig\|fill_holes\|dilation_radius\|erosion_radius' src tests README.md docs`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The step notation, voxel-radius resolution, and axis units, which every story uses

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Tests (write first, must fail)

- [X] T002 [P] Write `tests/unit/test_postprocess_steps.py` for the notation of `contracts/postprocess-notation.md` (C-PP-4, C-PP-5) with voxel radii only: every op parses (`fill`, `close:3`, `open:2.5`, `dilate:1`, `erode:4`, `largest`, `margin:3`, `invert`), case and whitespace are ignored (` Close : 3 , FILL `), a list of step strings parses like the comma form, `default` → `PostProcessSpec(steps=None)` and `none`/`""`/`[]` → `steps=()`; `str(step)` round-trips (C-PP-5); `PostProcessError` naming the offending step for: unknown op (`blur:3`), missing radius (`close`), forbidden radius (`fill:2`, `largest:1`, `invert:1`), radius `0`, `-1`, `abc`, unknown unit (`3furlong`), `default,fill`, `none,fill`; `resolve_steps` with voxel radii gives `radius_voxels == (r, r, r)` and `sampling == (1, 1, 1)` and `to_record()` == `{"op", "radius", "radius_voxels"}`; `PostProcessSpec.inherit` returns the saved steps for `default` (source `prompt_file`), `()` with source `default` when nothing is saved, and leaves explicit steps and `none` unchanged
- [X] T003 [P] Add to `tests/unit/test_reader.py` a test that `OmeZarrReader.axis_units` returns the axes' units (`["micrometer"] * 3` for a store written with units, `[None] * 3` without), and to `tests/unit/test_writer.py` a test that the written output's multiscale axes carry the input's units (FR-013); extend `write_ome_zarr` in `tests/conftest.py` with an optional `units: tuple[str | None, ...] | None = None` argument passed to `Axis(..., unit=...)` (default unchanged)

### Implementation

- [X] T004 Create `src/ome_zarr_masker/postprocess/steps.py` (data-model.md): `PostProcessError(ValueError)`; frozen dataclasses `Radius(value, unit, text)`, `PostProcessStep(op, radius)` with `__str__` in the shared notation, `PostProcessSpec(steps, source)` with `inherit(saved)`, `ResolvedStep(step, radius_voxels, sampling)` with `to_record()`; `parse_steps(value: str | Sequence[str] | None, source="cli") -> PostProcessSpec` implementing the grammar of `contracts/postprocess-notation.md` (units are parsed and validated here; physical-radius resolution is added in US2: until then `resolve_steps` raises `PostProcessError("physical radii ...")` for a radius with a unit); `resolve_steps(steps, scale, axis_units) -> tuple[ResolvedStep, ...]` for voxel radii. Make T002 pass
- [X] T005 [P] Add `axis_units: list[str | None]` to `OmeZarrReader` in `src/ome_zarr_masker/io/reader.py` (from `ms.axes[i].unit`), and pass `unit=reader.axis_units[i]` to `Axis(...)` in `_image_model` in `src/ome_zarr_masker/io/writer.py`. Make T003 pass

**Checkpoint**: `uv run --no-sync pytest -q tests/unit/test_postprocess_steps.py tests/unit/test_reader.py tests/unit/test_writer.py` passes; full login-node suite still green

---

## Phase 3: User Story 1 - Clean up a mask with an ordered sequence of steps (Priority: P1) 🎯 MVP

**Goal**: `mask --postprocess close:3,fill,largest,margin:3` applies the steps in order with ball-shaped morphology; the old options are gone; `default` (no saved steps yet) means no steps.

**Independent Test**: quickstart.md steps 2–3: each step equals a whole-volume reference; the user's sequence fixes a gap plane, a hole and a fragment; CLI options and errors behave per `contracts/cli.md`.

### Tests for User Story 1 (write first, must fail)

- [X] T006 [P] [US1] Rewrite `tests/unit/test_morphology.py` for `apply_steps(mask, resolved, *, workers=None, slab=None)` (C-PP-1, C-PP-2): on small random and structured 3D masks, each of `dilate`/`margin`/`erode`/`close`/`open` with radii 1, 2.5, 3 and 6 equals a reference computed over the whole volume with an explicit ellipsoid structure `{d: Σ(d_i/r_i)² ≤ 1}` (dilate/margin: `binary_dilation`; erode: `binary_erosion` with `border_value=0`; close: reference dilation then erosion on the volume padded by `ceil(r)` with background, cropped back, then OR-ed with the input; open: erosion then dilation, AND-ed with the input); the result is identical for `workers` 1 and 4 and for slab sizes 1, 7 and the full depth, and for radii on both sides of the structure/distance-transform switch (ball volume 400); `close` keeps a sample that touches the volume edge (no voxel of the input removed) and `open` adds none; `fill` equals `binary_fill_holes`; `largest` keeps the largest 26-connected component (diagonal bridges count), keeps the first in scan order on a tie, leaves an empty mask empty; `invert` complements, and steps after it act on the inverted mask; order matters (`close:3,largest` vs `largest,close:3` differ on a crafted mask); repeated steps apply each time; the user's sequence `close:3,fill,largest,margin:3` on a sphere with a one-voxel gap plane, an interior hole and a detached fragment closes the gap, fills the hole, drops the fragment and adds the margin (SC-001)
- [X] T007 [P] [US1] Add `postprocess` cases to `tests/contract/test_cli_mask.py` (contracts/cli.md) with the `stub_sam2` fixture: `--invert`, `--fill-holes`, `--no-fill-holes`, `--dilate 1`, `--erode 1` are usage errors (exit 2) whose stderr names `--postprocess`; `--postprocess blur:3` and `--postprocess fill:2` exit 1 before segmentation (stub not called), one stderr line naming the step and `--postprocess`, no output; `--postprocess close:1,fill` writes an output equal to applying `apply_steps` to the raw consensus (obtained by `--postprocess none`); with no option the output equals `--postprocess none` (no implicit fill, FR-004); `run_record.json` `config.postprocess` is `{"source": "cli", "steps": [{"op": "close", "radius": "1", "radius_voxels": [1.0, 1.0, 1.0]}, {"op": "fill", "radius": null, "radius_voxels": null}]}` and `{"source": "default", "steps": []}` by default; the input log contains the same steps
- [X] T008 [P] [US1] Update `tests/integration/test_us5_postprocess.py` and `tests/unit/test_config.py` to the new notation: replace `PostProcessConfig(...)` and old flags with `--postprocess` strings / `PostProcessSpec`, keeping each test's intent (fill on/off, dilation, erosion, invert last); invert now only via an `invert` step

### Implementation for User Story 1

- [X] T009 [US1] Rewrite `src/ome_zarr_masker/postprocess/morphology.py`: `apply_steps(mask, resolved, *, workers=None, slab=None) -> np.ndarray` applying `ResolvedStep`s in order (research R3–R4): `_ellipsoid(radius_voxels)` structure; `_dilate`/`_erode` per slab along axis 0 with a halo of `ceil(r_0)` planes on a `ThreadPoolExecutor` (`workers` default `min(os.cpu_count(), 8)`, slab default 64 planes), using `binary_dilation`/`binary_erosion` with the explicit structure when it has ≤ 400 voxels, else `distance_transform_edt` with `sampling` (dilate: `edt(~m) <= r`; erode: pad the slab with one background voxel, `edt(m) > r`); `close` = dilate on the volume padded by `ceil(r)` background planes per axis, erode, crop, OR with the input (never removes); `open` = erode, dilate, AND with the input (never adds); `margin` = dilate; `fill` = `binary_fill_holes`; `largest` = `label` with a 3×3×3 structure + `bincount`, first maximum; `invert` = `~`. Module docstring documents order and border rules. Make T006 pass
- [X] T010 [US1] In `src/ome_zarr_masker/config.py` remove `PostProcessConfig`; `RunConfig.postprocess: PostProcessSpec` (default `parse_steps("default", source="default")`); `RunConfig.to_record()["postprocess"]` = `{"source", "steps": [...]}` using resolved steps when set (`RunConfig.resolved_postprocess: tuple[ResolvedStep, ...] | None`, filled by the pipeline) else the parsed steps with `radius_voxels: null`; remove `PostProcessConfig` from `src/ome_zarr_masker/__init__.py` exports
- [X] T011 [US1] In `src/ome_zarr_masker/engine/pipeline.py`: after the level is resolved and before segmentation, resolve `config.postprocess` (`default` → `inherit(prompts.postprocess)`, which is `None` until US3 → no steps) with `resolve_steps(steps, reader.level_transform(level)[0], reader.axis_units)`, raising `PostProcessError` before any sweep; store the resolved steps on the record; replace `postprocess_mask(...)` with `apply_steps(consensus, resolved)` when non-empty
- [X] T012 [US1] In `src/ome_zarr_masker/cli.py`: remove `--fill-holes/--no-fill-holes`, `--dilate`, `--erode`, `--invert` from `mask`; add `--postprocess` (default `"default"`, help listing ops, units and the `default`/`none` keywords) inside a mutually exclusive group that T030 extends with `--postprocess-file`; make argparse report the removed options with a hint (a hidden action per removed flag that calls `parser.error("... was removed; use --postprocess ...")`); build `RunConfig(postprocess=parse_steps(args.postprocess))` catching `PostProcessError` (exit 1, `error: --postprocess: ...`); catch `PostProcessError` from `run_masking` as a domain error (exit 1)
- [X] T013 [US1] In `src/ome_zarr_masker/api.py`, `OrganMaskPredictor.predict(postprocess: str | Sequence[str] | None = None)` → `parse_steps(postprocess, source="api")` (`None`/`default`/`none` → no steps); in `src/ome_zarr_masker/interactive.py` pass the same type through `preview(postprocess=...)` (session-level steps come in US3)
- [X] T014 [US1] Run `uv run --no-sync ruff check src tests`, `ruff format`, and `uv run --no-sync pytest -q -m "not real_backend and not slow"`; fix until green. Commit "feat(postprocess): apply an ordered sequence of steps (011 US1)"

**Checkpoint**: The user's sequence works from the command line with voxel radii (MVP)

---

## Phase 4: User Story 2 - Give radii as physical sizes (Priority: P2)

**Goal**: Radii with a unit are converted per axis from the run level's scale and axis units.

**Independent Test**: quickstart.md steps 1–2 (units): a `margin:200um` gives the same physical thickness at two levels; anisotropic levels give ellipsoids; unit-less axes and sub-voxel radii are rejected.

### Tests for User Story 2 (write first, must fail)

- [X] T015 [P] [US2] Add to `tests/unit/test_postprocess_steps.py` physical-radius resolution cases: `margin:200um` on axes `micrometer` with scale `(63.0872, 63.0408, 63.0408)` → `radius_voxels ≈ (3.170, 3.173, 3.173)` and `sampling == scale`; `0.2mm` equals `200um`; `µm`/`UM` accepted; axes in `millimeter` convert correctly; `nanometer`/`centimeter`/`meter` factors; `None` units → `PostProcessError` saying the store has no axis units and suggesting a voxel radius; a non-length unit (`second`) rejected; `margin:10um` at 63 µm voxels (< 1 voxel on every axis) rejected with the voxel size in the message; a radius ≥ 1 voxel on one axis only is accepted
- [X] T016 [P] [US2] Add to `tests/unit/test_morphology.py` an anisotropic case: with `sampling=(2.0, 1.0, 1.0)` and a physical radius of 4, dilation equals the reference ellipsoid with semi-axes `(2, 4, 4)` voxels, for both the structure and the distance-transform paths
- [X] T017 [P] [US2] Add `tests/integration/test_postprocess_units.py` (stub backend, synthetic store with `units=("micrometer",)*3` and scales doubling per level): runs at level 0 and level 1 with `--postprocess margin:<4 level-1 voxels in µm>`; the margin's physical thickness, measured on the written level-0 output, differs by at most one run-level voxel per axis between the two runs (SC-002, C-PP-3); a store without units and `margin:200um` exits 1 before segmentation

### Implementation for User Story 2

- [X] T018 [US2] In `src/ome_zarr_masker/postprocess/steps.py`, implement physical resolution in `resolve_steps` (research R2): metre factors for the CLI units and for the OME-Zarr length units (`angstrom` … `kilometer`, plus `inch`, `foot`, `yard`, `mile`, `parsec` as per the OME 0.5 list); `radius_voxels_i = R_m / (scale_i × unit_m(axis_i))`, `sampling = scale × unit factor relative to R's unit` (so `edt(..., sampling) <= R` in R's unit); rejections per T015. Make T015–T017 pass
- [X] T019 [US2] Run lint and the login-node suite; fix until green. Commit "feat(postprocess): accept physical radii converted per axis (011 US2)"

**Checkpoint**: Physical radii work at any level and on anisotropic voxels

---

## Phase 5: User Story 3 - Choose the steps interactively and keep them with the prompts (Priority: P3)

**Goal**: Prompt files carry saved steps; `default` inherits them; the interactive session loads/saves prompt files and holds editable steps in a napari panel.

**Independent Test**: quickstart.md step 4: session with `postprocess` → `set_postprocess` → `save_prompts` → `mask` with that prompt file and no `--postprocess` equals the session's export (SC-007).

### Tests for User Story 3 (write first, must fail)

- [ ] T020 [P] [US3] Add to `tests/unit/test_prompts.py`: `load_prompt_file` reads an optional `"postprocess"` list into `PromptSet.postprocess` (tuple of steps), `None` when absent or `null`; an invalid saved step raises `PromptError`/`PostProcessError` naming the prompt file and the step; `"default"`/`"none"` inside a file are rejected; `save_prompt_file(path, prompt_set)` writes the feature 008 format (`level`, `objects` with `points` and one `box` per object) plus `"postprocess"` (list of step strings, or omitted when `None`, `[]` when empty) and round-trips through `load_prompt_file` (points, labels, boxes on several frames, obj_ids, level, steps)
- [ ] T021 [P] [US3] Add CLI cases to `tests/contract/test_cli_mask.py`: a prompt file with `"postprocess": ["close:1", "fill"]` and no `--postprocess` applies those steps (record source `prompt_file`); `--postprocess none` applies none (source `none`); `--postprocess dilate:1` replaces them (source `cli`); an invalid saved step exits 1 before segmentation naming the prompt file
- [ ] T022 [P] [US3] Write `tests/integration/test_postprocess_prompts.py` (stub backend, HTTP not needed): `InteractiveSession(store, level=0, prompts_path=p, postprocess="close:1,fill")` exposes the steps; `set_postprocess("close:1,fill,largest")` replaces them and an invalid value raises `PostProcessError` keeping the previous steps; previews and `export` use the current steps (equal to `predict(postprocess=...)`); `save_prompts()` writes `p` with the prompts and the current (final) steps; `main(["mask", store, out, "--prompts", p, "--level", "0"])` equals the session's export (SC-007); a new session on the same `prompts_path` with no `postprocess` loads the prompts (converted to its level when opened at another level) and the saved steps; with no saved steps and no `postprocess` the session has no steps; `main(["interactive", store, "--postprocess", "blur"])` exits 1 before opening a viewer (launch monkeypatched)

### Implementation for User Story 3

- [ ] T023 [US3] In `src/ome_zarr_masker/prompts/model.py`: add `PromptSet.postprocess: tuple[PostProcessStep, ...] | None = None`; `load_prompt_file` parses the optional `"postprocess"` key (list of strings; keywords rejected) with errors prefixed by the file path; add `save_prompt_file(path, prompt_set) -> Path` writing `{"level", "objects", "postprocess"?}` (group prompts by `obj_id`; each box in its own object with the same `obj_id`; points as `{"frame", "xy", "label"}`). Make T020 pass
- [ ] T024 [US3] In `src/ome_zarr_masker/engine/pipeline.py` and `src/ome_zarr_masker/cli.py`, resolve `default` with `PostProcessSpec.inherit(prompts.postprocess)` (source `prompt_file`); include the source in the record. Make T021 pass
- [ ] T025 [US3] In `src/ome_zarr_masker/interactive.py`: `InteractiveSession.__init__(..., *, prompts_path=None, postprocess=None, predictor=None)`; when `prompts_path` exists, load it with `load_prompt_file`, convert its prompts to the session level (`PromptSet.resolved_between`, feature 008) into `_points`/`_boxes`, and use its saved steps when `postprocess` is `None`/`"default"`; store `self.postprocess: PostProcessSpec` (validated with `parse_steps`, and resolved once against the reader to fail early); `set_postprocess(value)` (validate, resolve, replace; keep previous on error); `preview(postprocess=None)` and `export` use `self.postprocess` unless overridden; `save_prompts(path=None) -> Path` builds a `PromptSet` at the session level from `_points`/`_boxes` with `postprocess=self.postprocess.steps or ()` and calls `save_prompt_file` (default path `self.prompts_path`, else `prompts.json`). Make T022 pass (except the CLI case)
- [ ] T026 [US3] In `src/ome_zarr_masker/cli.py`, add to `interactive`: `--prompts FILE` (default `prompts.json`), and the mutually exclusive `--postprocess` (default `default`) / `--postprocess-file`; validate before constructing the session and pass `prompts_path`/`postprocess`; catch `PostProcessError`/`PromptError` (exit 1). Make the CLI case of T022 pass
- [ ] T027 [US3] In `InteractiveSession.launch` (`src/ome_zarr_masker/interactive.py`): add a dock widget "Post-processing" (qtpy `QLineEdit` pre-filled with `",".join(map(str, steps))`, an "Apply" button calling `set_postprocess` and showing errors in a `QMessageBox` while restoring the previous text, and a "Save prompts" button calling `save_prompts` and reporting the path in the status bar); bind `w` to the same save after syncing prompts from the layers; pre-populate the point/box layers with prompts loaded from `prompts_path`; update the docstring's key list (`w`) and README later. (GUI wiring is not unit-tested, like the rest of `launch`; keep logic in the tested session methods)
- [ ] T028 [US3] Run lint and the login-node suite; fix until green. Commit "feat(interactive): edit post-processing in a panel and save it with the prompts (011 US3)"

**Checkpoint**: Steps tuned in a session are reused by `mask` from the prompt file

---

## Phase 6: User Story 4 - Reuse one sequence everywhere and reproduce it (Priority: P4)

**Goal**: `--postprocess-file`; identical results across CLI, file, prompt file, API and session; reruns from the record reproduce the mask.

**Independent Test**: quickstart.md step 5.

### Tests for User Story 4 (write first, must fail)

- [ ] T029 [P] [US4] Add to `tests/integration/test_postprocess_prompts.py`: `--postprocess-file steps.json` (`{"postprocess": ["close:1", "fill"]}`) equals `--postprocess close:1,fill` (record source `file`); a prompt file with saved steps passed as `--postprocess-file` works; giving both options is a usage error (exit 2) for `mask` and `interactive`; missing, unreadable or malformed files (no `"postprocess"` key, not a list, invalid step) exit 1 before segmentation naming the file; the same steps via CLI, file, prompt file, `predict(postprocess=...)` and `InteractiveSession.export` give identical masks (SC-005, C-API-PP-1); rerunning `mask` with `--postprocess` built from the record's `[s["op"] + (":" + s["radius"] if s["radius"] else "") ...]` reproduces the mask exactly (SC-004); the input log lists the steps and their source

### Implementation for User Story 4

- [ ] T030 [US4] In `src/ome_zarr_masker/postprocess/steps.py` add `load_postprocess_file(path) -> PostProcessSpec` (source `file`, errors prefixed by the path); in `src/ome_zarr_masker/cli.py` add `--postprocess-file` to the mutually exclusive groups of `mask` and `interactive` and use it when given; in `src/ome_zarr_masker/input_log.py` (via `record_config`) make sure the recorded config includes the post-processing source and steps. Make T029 pass
- [ ] T031 [US4] Run lint and the login-node suite; fix until green. Commit "feat(cli): read post-processing steps from a file (011 US4)"

**Checkpoint**: All stories work independently and together

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T032 [P] Write `tests/performance/test_postprocess_perf.py` (`@pytest.mark.slow`): synthetic 941 × 874 × 874 bool mask (a large ellipsoid with a gap plane, holes and fragments), `apply_steps` with `close:3,fill,largest,margin:3` resolved at voxel radii; assert wall time < 300 s and peak RSS (`resource.getrusage`) < 16 GiB (SC-006); print both. Run it with the rest of `-m "slow or real_backend"` via `salloc -p mit_normal_gpu -A mit_general --gres=gpu:1 -c 8 --mem=32G -t 01:00:00 srun --chdir=<repo> uv run --no-sync pytest -q -m "slow or real_backend"` and record the numbers in research.md R4
- [ ] T033 [P] Update `README.md`: replace the post-processing option docs with `--postprocess`/`--postprocess-file` (steps table, voxel vs physical radii and units, order matters, `default`/`none`, ball shapes, `close`/`open` border rule, the user's example `close:3,fill,largest,margin:200um`), the prompt file's `"postprocess"` key, the interactive panel and `w`/`--prompts`, and a note under the prompt-file section that placing prompts on several planes (frames) reduces dropouts in multi-axis sweeps (FR-014); remove `--invert`/`--fill-holes`/`--dilate`/`--erode` mentions
- [ ] T034 [P] Update `docs/run-record.md`: the new `config.postprocess` shape (`source`, `steps` with `op`, `radius`, `radius_voxels`) and the axes' units in the output metadata
- [ ] T035 Write a real-data check outside the test suite (not under `tests/`, so pytest never collects it): `validation/dandi_001278_postprocess.py` plus `validation/run_dandi_001278.sh` (an `salloc -p mit_normal_gpu -A mit_general --gres=gpu:1 -c 8 --mem=32G -t 30` + `srun uv run --no-sync python validation/dandi_001278_postprocess.py` wrapper writing to a scratch output directory given as `$1`). The script uses the real, small OME-Zarr asset of dandiset 001278 `sourcedata/raw/sub-Hb1/micr/sub-Hb1_sample-lefthemi+ICblock+punch1+piece2_uCT.ome.zarr` (asset `7fdc9b48-aca4-4505-bcb7-4a92330136a6`, read remotely from `https://dandiarchive.s3.amazonaws.com/zarr/8507935b-39a0-4ce4-87da-58906eebdb74/`; 4 levels, uint16, micrometre axes; level 2 = 251 × 256 × 140 at 35.94 µm), at `--level 2`: (1) derive a positive prompt automatically from the level-2 data (threshold the middle z frame at its Otsu level, take the largest component's most interior voxel by distance transform) and write a prompt file with `"level": 2` and saved steps `["close:100um", "fill", "largest", "margin:72um"]`; (2) run `ome-zarr-masker mask URL OUT/default.ome.zarr --prompts p.json --level 2 --axes z,y,x --direction forward_reverse` (no `--postprocess`, so the saved steps are inherited) and the same with `--postprocess none` into `OUT/raw.ome.zarr`; (3) check and report as JSON on stdout, exiting 1 on any failure: both exit 0 and pass `ome-zarr-models` validation; the run record's `config.postprocess.source == "prompt_file"` and `radius_voxels ≈ 100/35.94` and `72/35.94` per axis; the output axes keep `micrometer`; `apply_steps` applied to the raw level-2 mask with the resolved steps equals the default run's level-2 output voxel for voxel; the post-processed mask has one 26-connected component, no 3D holes, and contains the raw mask; the mask is non-empty and not the whole volume; also print the Dice with an Otsu-threshold mask of the volume as an informative number (not a pass/fail). Document how to run it in `quickstart.md` (step 8) and record its result in the validation record
- [ ] T036 Run `uv run --no-sync ruff check src tests`, `ruff format --check`, the login-node suite, and the `salloc` slow/real_backend run (must be ≥ the 48 baseline tests passing plus the new perf test); walk quickstart.md steps 1–7, append a validation record to `specs/011-ordered-postprocessing/quickstart.md`. Commit "docs: document ordered post-processing (011)"

---

## Dependencies & Execution Order

- **Setup (T001)** → **Foundational (T002–T005)** → US1 → US2 → US3 → US4 → Polish
- US2 needs US1's pipeline resolution (T011) to exercise physical radii end to end; its unit tests (T015, T016) can be written alongside US1
- US3 needs US1's CLI/pipeline wiring; US4 needs US3's prompt-file steps (a prompt file passed as `--postprocess-file`, parity including prompt files)
- Within each story: tests first and failing → implementation → lint + suite + commit

### Parallel Opportunities

- T002 and T003 (different test files); T004 and T005 (different modules)
- T006, T007, T008 (three test files)
- T015, T016, T017
- T020, T021, T022
- T032, T033, T034, T035

---

## Parallel Example: User Story 1

```text
Task: "T006 Rewrite tests/unit/test_morphology.py"
Task: "T007 Add postprocess cases to tests/contract/test_cli_mask.py"
Task: "T008 Update tests/integration/test_us5_postprocess.py and tests/unit/test_config.py"
```

## Parallel Example: User Story 3

```text
Task: "T020 Prompt-file steps tests in tests/unit/test_prompts.py"
Task: "T021 Inheritance cases in tests/contract/test_cli_mask.py"
Task: "T022 Session tests in tests/integration/test_postprocess_prompts.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Setup and Foundational
2. US1: ordered steps from the command line, voxel radii
3. Validate with quickstart steps 2–3: the user's clean-up runs in one command

### Incremental Delivery

1. US1 (MVP), committed
2. US2 physical radii, committed
3. US3 interactive panel and steps in prompt files, committed
4. US4 post-processing files and parity, committed
5. Polish: performance on a compute node, docs, validation, committed
