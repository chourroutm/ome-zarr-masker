# Feature Specification: Bundled OME-Zarr Validation Dependency

**Feature Branch**: `003-bundled-ome-zarr-validation`

**Created**: 2026-06-15

**Status**: Draft

**Input**: User description: "include ome-zarr-models as a dependency. at the moment, it states that \"ome-zarr-models must be importable and its ome-zarr-models validate CLI on PATH\""

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Validate inputs after a plain install (Priority: P1)

A user installs ome-zarr-masker into a clean environment and immediately runs a masking
operation on a valid OME-Zarr v0.5 store. Input validation runs successfully without the user
having to install anything else or arrange for any separate validator command to be reachable on
their system path.

**Why this priority**: This is the core of the request. Today validation depends on an external
`ome-zarr-models validate` command being discoverable on `PATH`, which is a fragile, easy-to-miss
setup step. Making validation work from the plain install is the whole point of the feature and
delivers value on its own.

**Independent Test**: Install the package into a fresh environment, run a masking operation on a
known-valid OME-Zarr v0.5 store, and confirm validation passes and the run proceeds without any
additional environment setup.

**Acceptance Scenarios**:

1. **Given** a clean environment with only ome-zarr-masker installed, **When** the user runs a
   masking operation on a valid OME-Zarr v0.5 store, **Then** input validation passes and the run
   proceeds.
2. **Given** the same environment with no `ome-zarr-models` validator command reachable on `PATH`,
   **When** the user runs the same operation, **Then** validation still passes (it does not depend
   on a command being on `PATH`).
3. **Given** an invalid or malformed OME-Zarr store, **When** the user runs a masking operation,
   **Then** validation fails with a clear, actionable error message and the run does not proceed.

---

### User Story 2 - Accurate setup documentation (Priority: P2)

A user reading the README and quickstart sees that input validation is included with the package
and is not told to ensure any separate validator command is on their system path.

**Why this priority**: The current documentation states a prerequisite that the feature removes.
Leaving stale instructions in place would confuse users and undermine the change, but the
behavioral fix (US1) delivers value even before docs are updated.

**Independent Test**: Review the README, quickstart, and data-model documentation and confirm no
remaining instruction requires a validator command on `PATH`, and that validation is described as
included with the package.

**Acceptance Scenarios**:

1. **Given** the project documentation, **When** a user reads the setup/prerequisites sections,
   **Then** there is no instruction to place or verify a validator command on `PATH`.
2. **Given** the project documentation, **When** a user reads how inputs are validated, **Then** it
   states that validation is provided by the installed package.

---

### User Story 3 - Predictable validation regardless of environment (Priority: P3)

A user has an unrelated or differently-versioned `ome-zarr-models` command already present on their
system path. Running ome-zarr-masker still validates inputs using the version bundled with the
package, so behavior is consistent and reproducible.

**Why this priority**: Removes a subtle source of inconsistent results between machines. Valuable
for reproducibility but secondary to simply making validation work from a plain install.

**Independent Test**: Place a conflicting or differently-versioned validator command earlier on
`PATH`, run a masking operation, and confirm validation behavior matches the bundled dependency
rather than the on-`PATH` command.

**Acceptance Scenarios**:

1. **Given** a conflicting validator command on `PATH`, **When** the user runs a masking operation,
   **Then** validation uses the version declared as the package dependency, not the on-`PATH`
   command.

---

### Edge Cases

- What happens when the validation dependency is somehow absent from the environment (for example a
  broken or partial install)? The tool MUST fail with a clear message that names the missing
  dependency and how to resolve it, rather than a generic "command not found" error.
- How does the system handle a store that exists on disk but is not a valid OME-Zarr v0.5 store? It
  MUST reject it with an actionable validation error (no behavior regression from today).
- How does the system handle a path that does not exist at all? It MUST report that the input store
  does not exist (no behavior regression from today).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Installing ome-zarr-masker MUST bring in everything required to validate OME-Zarr
  v0.5 inputs, with no separate installation step and no requirement to place or verify a validator
  command on the system `PATH`.
- **FR-002**: Input validation MUST succeed or fail based solely on the package's declared
  dependency, not on the presence, absence, or version of any external validator command on `PATH`.
- **FR-003**: Valid OME-Zarr v0.5 stores that pass validation today MUST continue to pass after the
  change (no false rejections).
- **FR-004**: Invalid, malformed, or missing stores MUST continue to be rejected with a clear,
  actionable error message (no weakening of validation).
- **FR-005**: If the required validation dependency is unavailable at runtime, the tool MUST fail
  with a message that identifies the missing dependency and how to install it.
- **FR-006**: Project documentation (README, quickstart, and data-model) MUST be updated to remove
  the "validator command must be on `PATH`" prerequisite and to state that validation is provided by
  the installed package.
- **FR-007**: The package MUST declare a minimum compatible version of the validation dependency so
  that validation behavior is reproducible across installs.

### Key Entities *(include if feature involves data)*

- **OME-Zarr v0.5 store**: The input volume the user wants to mask; must be validated as a
  conformant OME-Zarr v0.5 store before any masking work begins.
- **Validation dependency**: The bundled OME-Zarr metadata/validation capability that ome-zarr-masker
  relies on; declared as a package dependency with a minimum compatible version.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from a fresh install to a successful validated masking run on a valid
  store with zero manual environment setup beyond installing the package.
- **SC-002**: 100% of inputs that validate successfully today continue to validate, and 100% of
  inputs that are rejected today continue to be rejected (no regression in validation outcomes).
- **SC-003**: With no validator command reachable on `PATH`, validation of a valid store still
  succeeds in 100% of attempts (the on-`PATH` prerequisite is fully eliminated).
- **SC-004**: The project documentation contains zero remaining instructions requiring a validator
  command on `PATH`.
- **SC-005**: Per-run input-validation time does not increase relative to the current approach when
  measured on the same valid store and environment.

## Assumptions

- The intent is to rely on the already-declared `ome-zarr-models` package (an existing runtime
  dependency) for validation rather than on an external command discovered via `PATH`; whether
  validation is performed in-process or by invoking a package-bundled entry point resolved without
  `PATH` is an implementation choice deferred to planning, provided no `PATH` prerequisite remains.
- OME-Zarr v0.5 remains the only supported input version; this feature does not change which
  versions are accepted.
- Existing validation outcomes and error semantics (valid passes, invalid/missing rejected with a
  clear message) are preserved; only the dependency on a command being on `PATH` is removed.
- The validation capability needed by this feature is available from the installed `ome-zarr-models`
  package at the declared minimum version. If that package only exposes validation as a console
  script, planning will resolve that script from the installed package rather than from `PATH`.
