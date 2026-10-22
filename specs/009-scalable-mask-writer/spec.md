# Feature Specification: Scalable Mask Writer

**Feature Branch**: `009-scalable-mask-writer`

**Created**: 2026-10-16

**Status**: Draft

**Input**: User description: "Fix GitHub issue #3 (chourroutm/ome-zarr-masker): the OME-Zarr mask writer does not scale to large volumes. It materializes every pyramid level fully in memory before writing, and writes each level as a single uncompressed chunk. Reported reproduction: a level-0 shape of (7526, 6985, 6985) with 5 levels needed ~370 GB RAM to write the output mask and produced 391 GB on disk for a highly compressible binary mask; the single-chunk-per-level layout also can't be read lazily by viewers or downstream tools. Goal: handle large real-world volumes without the whole output pyramid fitting in memory, and produce compressed, lazily-readable OME-Zarr output comparable to well-formed OME-Zarr pyramids."

## Clarifications

### Session 2026-10-16

- Q: When writing each output level, should the mask copy the input level's own chunk and shard layout, or always use one fixed default layout? → A: Copy the input level's chunk and shard layout when that level is sharded; if the input level is not sharded, use the default sharded layout instead (64³ chunks in 1024³ shards). Output levels are always sharded.
- Q: Should this feature also add user-facing options to override the chunk and shard sizes, or keep the layout fully automatic for now? → A: Fully automatic for now; no chunk/shard-size options on the CLI or API (possible later feature).
- Q: What should limit the writer's peak memory when it writes shards in parallel? → A: Parallel within a fixed memory budget (8 GiB beyond the run-level mask): as many shards at once as fit, minimum one. An optional user-set worker count (CLI and API) overrides the budget-derived count.
- Q: Should the saved run record and the input log include the worker count and the chosen chunk/shard layout, or stay exactly as today? → A: The run record gains each level's chunk/shard layout; the worker count goes only in the input log.
- Q: How much progress should the writer report while it works? → A: One message per level plus periodic shard progress within each level (about every 10% of its shards), through the existing progress reporting (stderr with `--verbose`, the progress callback in the API).

### Session 2026-10-16 (during planning, after comparing with the user's DANDI workaround and ome-zarr-tools)

- Q: Which nearest-neighbour mapping should the writer use when resampling the run-level mask to other levels? → A: Physical nearest neighbour from each level's own scale and translation: each target voxel's centre is mapped into the run level and takes the source voxel whose centre is nearest, with exact ties going to the lower index. This replaces "identical to the current writer", which misplaced 6–25% of planes by one voxel on the real DANDI pyramid (half-pixel translations, non-exact ratios).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Mask a very large volume without running out of memory (Priority: P1)

A researcher masks a large, multi-level OME-Zarr volume (gigavoxels at full resolution), running the
segmentation at a coarse level that comfortably fits in memory. Writing the output mask, which must
also populate the much larger fine levels, completes on an ordinary workstation or node instead of
needing hundreds of gigabytes of RAM.

**Why this priority**: This is the reported incident. Segmentation itself finished fine; only
writing the result required ~370 GB of RAM, forcing a manual workaround. Without this fix the tool
cannot be used end-to-end on realistic large datasets.

**Independent Test**: Write a mask computed at a coarse level into a pyramid whose finest level is
many times larger than the computed mask, while measuring the writer's peak memory, and confirm it
stays bounded rather than growing with the finest level's size.

**Acceptance Scenarios**:

1. **Given** a mask computed at a coarse level of a multi-level input, **When** the output pyramid
   is written (including levels finer than the computed one), **Then** the writer's peak memory does
   not grow with the size of the largest level being written.
2. **Given** any input, **When** the output is written, **Then** every level's voxel values equal the
   physical nearest-neighbour resampling of the run-level mask (FR-006). For inputs without
   translations whose level shapes are exact multiples, this is identical to what the current writer
   produces.
3. **Given** a pyramid with half-pixel translations and non-exact shape ratios (like the DANDI input
   from the originating issue), **When** the output is written, **Then** each output voxel takes the
   run-level voxel that physically contains its centre (no one-voxel drift at the finer levels).

---

### User Story 2 - Get small output files that viewers can stream (Priority: P2)

A researcher opens the mask output in a volume viewer (e.g. neuroglancer, napari) or hands it to a
downstream tool. The output is stored compactly and can be read piece by piece, instead of each
level being one giant uncompressed block that must be read in full.

**Why this priority**: Directly addresses the 391 GB on-disk output and the unusable
single-block-per-level layout. Secondary to the memory failure, which blocks the run entirely.

**Independent Test**: Write a mask output and inspect each level's stored layout: it is split into
multiple pieces smaller than the level, those pieces are compressed, and a single piece can be read
without reading the whole level.

**Acceptance Scenarios**:

1. **Given** a written mask output, **When** each level's stored layout is inspected, **Then** the
   level is divided into multiple independently readable pieces (none spanning the whole level,
   unless the level is smaller than one piece) and its data is compressed.
2. **Given** a mask that is mostly background, **When** it is written, **Then** its on-disk size is
   a small fraction of its uncompressed size, and regions that are entirely background take
   essentially no space.

---

### User Story 3 - Output layout consistent with the input's (Priority: P3)

When an input level is stored as pieces grouped into larger storage units (sharded), the output mask
uses the same division for the corresponding level, so the two stores line up and are equally
convenient to work with downstream. Input levels that are not sharded are not copied; the output
always uses grouped storage units.

**Why this priority**: A consistency and ergonomics improvement on top of US1/US2, not required for
the tool to work on large data.

**Independent Test**: Write a mask against a sharded input with a known, non-default per-level
layout and confirm each output level uses the same piece and storage-unit sizes as the matching
input level; with an unsharded input, confirm the default sharded layout is used instead.

**Acceptance Scenarios**:

1. **Given** an input whose levels are sharded, **When** the mask is written, **Then** each output
   level uses the same piece size and storage-unit size as the corresponding input level.
2. **Given** an input level that is not sharded (including one stored as a single whole-level
   piece), **When** the mask is written, **Then** that output level uses the default sharded layout
   (64³ pieces grouped into 1024³ storage units) rather than copying the input.

### Edge Cases

- Levels coarser than the computed mask (downsampling) must be written with the same bounded memory
  as finer levels (upsampling), not only the upsampling direction that caused the reported incident.
- A level whose shape is not an exact multiple of its piece size (ragged edge pieces) must be written
  correctly.
- A level smaller than a single piece must still be written correctly.
- A fully background mask should produce an output that takes almost no space on disk.
- Existing safety guarantees must hold: refuse to replace an existing output unless overwriting is
  explicitly requested, and leave no partial output behind if writing fails part-way.
- The run record saved alongside the output keeps all its current content; its only addition is
  each level's chunk/shard layout (FR-012), and two runs that differ only in worker count produce
  identical run records.
- If a single storage unit is larger than the memory budget (e.g. a very large shard copied from the
  input), writing proceeds one unit at a time; the budget can't be met, and the user is told so
  rather than the write failing.
- A user-set worker count below one is rejected before anything is written.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST write each pyramid level of the output mask without materializing that
  level's full array in memory at once, in both the upsampling (finer than the computed mask) and
  downsampling (coarser) directions.
- **FR-002**: By default, System MUST keep its peak memory while writing the output within a fixed
  budget of 8 GiB beyond the run-level mask, by limiting how many storage units (shards) are written
  at the same time to as many as fit in that budget, and never fewer than one. Peak memory MUST NOT
  depend on the size of the level being written.
- **FR-003**: System MUST store each output level divided into multiple independently readable
  pieces, rather than as a single piece spanning the whole level (except where the level is smaller
  than one piece).
- **FR-004**: System MUST compress the stored output data.
- **FR-005**: System MUST NOT store data for pieces that are entirely background.
- **FR-006**: System MUST set every output voxel by physical nearest-neighbour resampling of the
  run-level mask. Using each level's scale and translation from the input's metadata (scale 1 and
  translation 0 when absent), map the target voxel's centre into the run level and take the source
  voxel whose centre is nearest, with exact ties going to the lower index. For inputs without
  translations and with exact shape ratios, the result MUST be identical to the current writer's.
- **FR-007**: System MUST reuse the corresponding input level's piece size and storage-unit size for
  each output level when that input level is sharded; when it is not sharded, System MUST use the
  default sharded layout (64³ pieces grouped into 1024³ storage units). Every output level MUST be
  sharded.
- **FR-008**: System MUST preserve the existing output guarantees: the same number of levels, shapes,
  axes and spatial transforms as the input; refuse to replace an existing output without explicit
  overwrite; no partial output on failure; the run record embedded with the output (extended only as
  in FR-012).
- **FR-009**: System MUST keep the output a valid OME-Zarr v0.5 image that the tool's own reader and
  validator accept.
- **FR-010**: System MUST NOT require any new mandatory CLI argument or API parameter; existing
  invocations keep working unchanged and receive the improvements automatically. The only new input
  is the optional worker count (FR-011); there are no chunk or shard size options.
- **FR-011**: Users MUST be able to set the number of storage units written in parallel (worker
  count) through an optional CLI option and a matching optional API parameter. When set, it replaces
  the budget-derived count from FR-002, so peak write memory becomes roughly that many storage units
  and the user takes responsibility for it. A worker count below one MUST be rejected with a clear
  error before any output is written.
- **FR-012**: System MUST record each output level's layout (piece shape, storage-unit shape, and
  compression) in the run record saved with the output. The worker count used for each level
  (user-set or budget-derived) MUST NOT appear in the run record; for CLI runs it MUST be recorded in
  the input log. API saves run after `predict()`'s logged invocation has closed, so for them it is
  reported through the save's progress callback instead.
- **FR-013**: System MUST report write progress through the existing progress reporting: one message
  when each level starts (naming the level, its shape, and its number of storage units), then a
  message about every 10% of that level's storage units completed. Progress never goes to stdout.

### Key Entities

- **Output level**: One pyramid level of the written mask. Gains an explicit piece layout and
  compression, where today it has one whole-level piece and no compression.
- **Piece layout**: How a level is divided into independently readable pieces, and how those pieces
  are grouped into larger storage units (sharding, always present in the output). Copied from the
  matching input level when it is sharded; otherwise the default (64³ pieces in 1024³ units).
  Recorded per level in the run record.
- **Worker count**: How many storage units are written at the same time. Derived from the memory
  budget unless the user sets it; recorded in the input log, not the run record.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Writing the output for a pyramid whose finest level is at least 64 times larger than the
  computed mask keeps peak memory within the run-level mask plus the write budget (8 GiB by default,
  or the proportionally scaled budget used in tests), instead of growing with the finest level.
- **SC-002**: For a typical organ mask (mostly background), the written output occupies less than 5%
  of its uncompressed size on disk.
- **SC-003**: Every output voxel equals an independent brute-force physical nearest-neighbour
  reference, both on translation-free test inputs (where it also equals the current writer) and on a
  scaled-down pyramid with the DANDI input's half-pixel translations and non-exact shape ratios.
- **SC-004**: A single piece of any output level can be read without reading the rest of that level.
- **SC-005**: For inputs small enough for the current writer, total time to write the output does not
  regress by more than 25%.
- **SC-006**: With a user-set worker count, the number of storage units written at the same time
  never exceeds that count.

## Assumptions

- Scope is the mask writer only. The segmentation and consensus steps upstream already hold only the
  computed (run-level) mask in memory, an accepted constraint since feature 001; the originating
  issue's own reproduction shows segmentation completing fine at a coarse level.
- The computed mask at the run level is assumed to fit in memory (as today); only the other levels'
  output, especially the finer ones, must not be fully materialized.
- No user-facing options for piece or storage-unit size are added in this feature (confirmed in
  Clarifications); the layout is chosen automatically (copied from a sharded input level, or the
  default). The issue lists such options as optional; they can follow as a separate feature. The
  only new user-facing input is the optional worker count (FR-011).
- The 8 GiB default write budget is an internal constant, not user-configurable; users who need a
  different trade-off set the worker count instead.
- Downstream compatibility: ome-zarr-tools' `apply_mask` (checked 2026-10-16 against its current
  source, dask 2026.7.1 / zarr 3.3.0) pairs mask and volume levels by name and requires equal shapes
  at the paired level, which this writer already guarantees (FR-008). It does not require the mask to
  share the volume's piece layout: it re-divides the masked result onto the volume's own grid before
  writing. A layout matching the volume is still the cheapest to read, and a single whole-level piece
  (today's output) forces it to load a whole level into memory, which is unusable at the reported scale.
- The default layout follows the issue's suggestion: 64³ pieces grouped into 1024³ storage units,
  with a compressor well suited to binary masks (exact compressor settings finalized during planning).
  Where a level is smaller than one storage unit, the unit is capped to the level's shape.
- The on-disk layout of outputs intentionally changes; outputs written by earlier versions remain
  readable and need no migration.
- Validating memory boundedness at the full reported scale (hundreds of GB) is impractical in
  automated tests; it is validated with a proportionally scaled-down scenario plus measurement of
  peak memory against a correspondingly scaled-down write budget.
- Remote (non-local) input/output stores remain out of scope, as for earlier features.
- The user's DANDI workaround (`finalize_mask.py`) and ome-zarr-tools' `from_images`/`upsample` use
  the same storage choices as this feature's default (64³ chunks, 1024³ shards, blosc
  zstd/3/bitshuffle, one write task per shard). Its other suggestions (closing, bright-region
  inclusion, keep-largest-component, margin after fill-holes, multi-plane prompting guidance) are
  out of scope here and candidates for a later post-processing feature.
- Feature 008's prompt conversion between levels now uses the same physical mapping (reworked
  2026-10-16): `geometry.nearest_index` and `OmeZarrReader.level_transform` are shared, so prompts and
  the written mask agree on which voxel a physical position belongs to.
