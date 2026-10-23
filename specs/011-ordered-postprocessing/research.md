# Research: Ordered Post-Processing Pipeline

Feature: `specs/011-ordered-postprocessing/spec.md`. Probed in the project venv (scipy, numpy,
zarr 3.3.0, ome-zarr-models 1.7) on the login node with small volumes; full-size targets are
measured on a compute node (R8).

## R1. Step notation and parsing

- **Decision**: One notation everywhere: a step is `op` or `op:R`; a sequence is a comma-separated
  string on the command line and a JSON list of the same step strings in files
  (`["close:3", "fill", "largest", "margin:200um"]`). Ops: `fill`, `close`, `open`, `dilate`,
  `erode`, `largest`, `margin`, `invert`; keywords `default` and `none` must stand alone.
  Parsing is case-insensitive, ignores whitespace around commas, and is done once into immutable
  `PostProcessStep` values before any segmentation (FR-008).
- **Rationale**: The same strings appear on the command line, in files, in the API and in the
  interactive panel, so users learn one syntax and a recorded sequence can be pasted back.
- **Alternatives considered**: Structured JSON objects per step (`{"op": "close", "radius": 3}`):
  clearer for machines but a second syntax to learn; the run record uses objects (R7) for the
  resolved form only. Ordered argparse flags: rejected in the design discussion (no position for
  defaults, no order in Python keyword arguments).

## R2. Radii and units

- **Decision**: `R` is a positive decimal number, optionally followed by a unit among `nm`, `um`,
  `µm`, `mm`, `cm`, `m` (case-insensitive). No unit = run-level voxels: the same radius on every
  axis. With a unit, the per-axis voxel radius is `R_m / (scale_axis × unit_m(axis))`, where
  `scale_axis` is the run level's scale and `unit_m(axis)` converts the axis's OME-Zarr unit
  (`micrometer`, `millimeter`, ... from the OME 0.5 length-unit list) to metres. Axes with no unit,
  or a non-length unit, reject physical radii. A physical radius whose voxel radius is < 1 on every
  axis is rejected (the step would do nothing).
- **Rationale**: FR-005/FR-006: the same physical size at any level, and correct on anisotropic
  levels (the user's DANDI level 3 is 63.09 × 63.04 × 63.04 µm). The DANDI store declares
  `micrometer` on all axes (checked), so physical radii work on real inputs.
- **Alternatives considered**: Converting with an isotropic mean voxel size (wrong for anisotropic
  data); accepting unit-less axes as micrometres (silently wrong for other units).

## R3. Structuring shape and border semantics

- **Decision**: The structuring shape for a step with per-axis voxel radii `r_i` is the ellipsoid
  `{d : Σ (d_i / r_i)² ≤ 1}` over integer offsets `d` (a ball when all `r_i` are equal, i.e. every
  voxel whose centre is within distance R, in physical units when R has one). `dilate:R` and
  `margin:R` add every voxel within that ellipsoid of the mask (identical results; both names
  kept, spec Assumptions). `erode:R` removes every mask voxel within that distance of background,
  with everything outside the volume counting as background. `close:R` = dilate then erode, and
  `open:R` = erode then dilate, but with the border chosen so that closing never removes a mask
  voxel and opening never adds one: the erosion inside `close` treats outside the volume as
  foreground, and the dilation inside `open` treats it as background.
- **Rationale**: A ball replaces the cross-iteration shape (FR-007). Without the closing border
  rule, `close` would eat a margin off any sample that touches the volume edge (the user's
  workaround, `binary_closing(..., border_value=0)`, has that defect). The spec's edge-case line
  "everything outside the volume counts as background" is refined accordingly (spec updated).
- **Verified**: on a 192³ sphere with a gap plane, dilation with an explicit ball structure and
  `distance_transform_edt(~mask) <= r` give identical masks for r = 3 and r = 8.

## R4. Morphology algorithm and performance

- **Decision**: Each dilation/erosion runs slab by slab along the first axis, each slab with a halo
  of `ceil(r_0)` planes, on a thread pool, so peak memory is bounded by a few slabs and the work is
  parallel. Per slab, the algorithm is chosen by structuring-shape size: an explicit ellipsoidal
  structure (`scipy.ndimage.binary_dilation/erosion`) when the shape has ≤ 400 voxels (about
  radius 4.5), otherwise a Euclidean distance transform with `sampling` set to the per-axis voxel
  size (`distance_transform_edt`), whose cost doesn't grow with the radius. Both give the same set
  (R3). `fill` (3D `binary_fill_holes`) and `largest` (`label` with 26-connectivity + `bincount`)
  run on the whole mask. `invert` is a negation.
- **Measured** (192³ = 7.1 M voxels, login node, one thread unless stated):

  | Operation | Time |
  |---|---|
  | dilate r=3, ball structure | 0.54 s |
  | dilate r=3, EDT | 1.46 s |
  | dilate r=8, ball structure | 8.84 s |
  | dilate r=8, EDT | 1.19 s |
  | dilate r=3, slabs on 1 / 4 threads | 0.59 s / 0.17 s |
  | fill holes | 0.23 s |
  | label + component sizes | 0.09 s |

  Scaled ×102 to the user's run level (941 × 874 × 874 = 719 M voxels): `close:3` ≈ 2 × 60 s on one
  thread (≈ 2 × 17 s on 4), `fill` ≈ 25 s, `largest` ≈ 10–20 s, `margin:3` ≈ 60 s (≈ 17 s on 4),
  so the user's sequence is ≈ 1.5 min on 4 threads, inside SC-006 (5 min).
- **Measured at full size** (compute node, 8 CPUs, `tests/performance/test_postprocess_perf.py`):
  `close:3,fill,largest,margin:3` on 941 × 874 × 874 in 47.5 s, peak RSS 12.1 GiB.
- **Rationale**: Ball structures are fastest for small radii but grow with r³; EDT is flat but uses
  ~20 bytes per voxel (float64 distances + int32 feature indices), so it runs per slab.
  The thread pool works because these scipy routines release the GIL (4 threads: 3.5× faster).
- **Alternatives considered**: EDT only (2.7× slower at r=3 and 14 GB at full size without slabs);
  ball structure only (minutes per step at physical radii that become large at fine levels);
  the third-party `edt` package (fast, but a new compiled dependency for a gain the slabs already
  give).

## R5. Where steps come from, and precedence

- **Decision**: `--postprocess` (default `default`) and `--postprocess-file` are mutually
  exclusive. Resolution, done once before segmentation:
  1. `--postprocess-file F` → the steps in F (source `file`);
  2. `--postprocess STEPS` other than `default` → those steps (source `cli`), `none` → no steps
     (source `none`);
  3. `default` → the prompt file's saved steps if present (source `prompt_file`), else no steps
     (source `default`).
  The Python API has no prompt file: `postprocess=None` or `"default"` → no steps unless the caller
  passes some; `InteractiveSession` resolves like the CLI (its prompt file's saved steps).
- **Rationale**: Implements spec clarifications Q1–Q2 and FR-004.

## R6. File formats

- **Decision**:
  - Prompt file (extends feature 008's format): optional top-level `"postprocess": [step, ...]`
    next to `"level"` and `"objects"`. Absent or `null` → no saved steps. `"default"` and `"none"`
    are not valid saved steps (an empty list means "no steps"), so a saved file never defers.
  - Post-processing file: a JSON object with a `"postprocess"` list; other keys are ignored, so a
    prompt file with saved steps can also be passed as `--postprocess-file`.
  - Saving from the interactive session writes `{"level", "objects", "postprocess"}` in the
    feature 008 format (one object per obj_id; one object per box frame, since the format holds one
    box per object), so `load_prompt_file` reads it back unchanged.
- **Rationale**: One key, one notation; files written by the session round-trip through the
  existing loader.

## R7. Records

- **Decision**: `run_record.json` `config.postprocess` becomes
  `{"source": "...", "steps": [{"op", "radius" (as given, string or null), "radius_voxels"
  (per-axis floats or null)}, ...]}`; the input log records the same object and, for `mask`, the
  raw option values. `docs/run-record.md` is updated.
- **Rationale**: FR-012; a recorded `radius` string can be pasted back into `--postprocess`.

## R8. Performance validation

- **Decision**: A `slow` performance test builds a synthetic 941 × 874 × 874 run-level mask with a
  gap plane, holes and fragments and runs `close:3,fill,largest,margin:3`; it must finish in under
  5 minutes and under 16 GiB peak RSS on a compute node (run through `salloc`, like the other slow
  tests). A small-volume equality test checks every step against a direct reference
  implementation (explicit ball structure, whole volume) for voxel and physical radii.

## R9. Axis units in the output (FR-013)

- **Decision**: `OmeZarrReader` exposes `axis_units` (`str | None` per axis) from the multiscale
  axes; the writer passes them to `Axis(name, type="space", unit=...)`.
- **Rationale**: The writer currently writes axes without units, so the output loses the input's
  physical meaning; probed: `ome_zarr_models.v05.axes.Axis` accepts `unit`.
