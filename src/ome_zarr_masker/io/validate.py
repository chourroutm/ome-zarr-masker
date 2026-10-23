"""Validate OME-Zarr v0.5 inputs in-process via the installed ``ome-zarr-models`` package (FR-001).

Validation uses ``ome_zarr_models.open_ome_zarr`` directly, mirroring the package's own ``validate``
CLI (which treats :class:`ome_zarr_models.exceptions.ValidationWarning` as an error). It therefore
depends only on the installed dependency, never on a validator command being discoverable on
``PATH`` (FR-002).
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from pathlib import Path

from .location import RemoteStoreError, StoreLocation, read_key, remote_errors

_MISSING_DEP_HINT = (
    "OME-Zarr validation requires the 'ome-zarr-models' package (>=1.6); "
    "install it with 'pip install ome-zarr-models'"
)


class ValidationError(RuntimeError):
    """Raised when an input fails OME-Zarr validation."""


def _describe_actual_version(read: Callable[[str], bytes | None]) -> str | None:
    """Best-effort sniff of the store's real Zarr/OME-Zarr version, for a clearer error message.

    Reads the raw group metadata directly (not via ``ome_zarr_models``), so this still works for
    stores that ``open_ome_zarr(..., version="0.5")`` rejects outright -- e.g. a v0.4 store, which
    uses Zarr format 2 (``.zgroup``/``.zattrs``) instead of the Zarr format 3 (``zarr.json``) that
    v0.5 requires, and so has no v3 group for the validator to even find. Returns ``None`` if the
    store doesn't look like recognizable OME-Zarr metadata at all. ``read(name)`` returns a root
    metadata document's bytes, or ``None`` if the store has no such document.
    """
    zarr_json = read("zarr.json")
    if zarr_json is not None:
        try:
            meta = json.loads(zarr_json)
            ome_version = meta.get("attributes", {}).get("ome", {}).get("version")
        except Exception:
            ome_version = None
        if ome_version:
            return f"OME-Zarr v{ome_version} (Zarr format 3)"
        return None

    if read(".zgroup") is not None:
        ome_version = None
        try:
            zattrs = json.loads(read(".zattrs") or b"")
            multiscales = zattrs.get("multiscales") or []
            if multiscales:
                ome_version = multiscales[0].get("version")
        except Exception:
            ome_version = None
        if ome_version:
            return f"OME-Zarr v{ome_version} (Zarr format 2)"
        return "Zarr format 2 (pre-v0.5 OME-Zarr storage layout)"

    return None


def _read_local(path: Path) -> Callable[[str], bytes | None]:
    def read(name: str) -> bytes | None:
        f = path / name
        return f.read_bytes() if f.exists() else None

    return read


def validate_ome_zarr(path: str | Path | StoreLocation) -> None:
    """Validate ``path`` as an OME-Zarr v0.5 store; raise ``ValidationError`` on failure (FR-001).

    Raises ``ValidationError`` if the store is missing or invalid, or if the ``ome-zarr-models``
    dependency is unavailable. ``path`` may be a remote URL (feature 010): it is validated with the
    same rules and messages (FR-006), and a store that can't be reached, doesn't exist or is
    forbidden raises :class:`RemoteStoreError` instead (FR-010).
    """
    location = StoreLocation.parse(path)
    if location.is_remote:
        _validate_remote(location)
        return
    path = location.path
    if not path.exists():
        raise ValidationError(f"input store does not exist: {path}")
    _validate(str(path), str(path), _read_local(path))


def _validate_remote(location: StoreLocation) -> None:
    """Remote branch: existence and the version sniff use store reads; then the same checks."""
    with remote_errors(location):
        store = location.open_store(read_only=True)

        def read(name: str) -> bytes | None:
            return read_key(store, name)

        if read("zarr.json") is None and read(".zgroup") is None:
            raise RemoteStoreError(
                f"{location.display}: not found (no OME-Zarr store at this location)",
                cause="not_found",
                location=location.display,
            )
        _validate(store, location.display, read, location)


def _validate(
    target, shown: str, read: Callable[[str], bytes | None], location: StoreLocation | None = None
) -> None:
    """Open ``target`` (a path string or store) with ome-zarr-models as v0.5, strictly."""

    try:
        from ome_zarr_models import open_ome_zarr
        from ome_zarr_models.exceptions import ValidationWarning
    except ImportError as exc:  # broken/partial install (FR-005)
        raise ValidationError(_MISSING_DEP_HINT) from exc

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", category=ValidationWarning)
            open_ome_zarr(target, version="0.5")
    except Exception as exc:
        if location is not None:
            mapped = _remote_failure(exc, location)
            if mapped is not None:
                raise mapped from exc
        actual = _describe_actual_version(read)
        if actual is not None:
            raise ValidationError(
                f"input at {shown} is {actual}, but ome-zarr-masker requires OME-Zarr v0.5 "
                "(Zarr format 3); convert the store to v0.5 before running this tool"
            ) from exc
        raise ValidationError(f"input is not a valid OME-Zarr v0.5 store: {exc}") from exc


def _remote_failure(exc: Exception, location: StoreLocation) -> RemoteStoreError | None:
    """A network/permission failure while validating, which isn't a validation result (FR-010).

    A missing *document* inside an existing store is a validation failure, not ``not_found``.
    """
    from .location import map_remote_error

    mapped = map_remote_error(exc, location)
    return mapped if mapped is not None and mapped.cause != "not_found" else None
