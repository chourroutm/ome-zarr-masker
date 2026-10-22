"""Validate OME-Zarr v0.5 inputs in-process via the installed ``ome-zarr-models`` package (FR-001).

Validation uses ``ome_zarr_models.open_ome_zarr`` directly, mirroring the package's own ``validate``
CLI (which treats :class:`ome_zarr_models.exceptions.ValidationWarning` as an error). It therefore
depends only on the installed dependency, never on a validator command being discoverable on
``PATH`` (FR-002).
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

_MISSING_DEP_HINT = (
    "OME-Zarr validation requires the 'ome-zarr-models' package (>=1.6); "
    "install it with 'pip install ome-zarr-models'"
)


class ValidationError(RuntimeError):
    """Raised when an input fails OME-Zarr validation."""


def _describe_actual_version(path: Path) -> str | None:
    """Best-effort sniff of the store's real Zarr/OME-Zarr version, for a clearer error message.

    Reads the raw group metadata directly (not via ``ome_zarr_models``), so this still works for
    stores that ``open_ome_zarr(..., version="0.5")`` rejects outright -- e.g. a v0.4 store, which
    uses Zarr format 2 (``.zgroup``/``.zattrs``) instead of the Zarr format 3 (``zarr.json``) that
    v0.5 requires, and so has no v3 group for the validator to even find. Returns ``None`` if the
    store doesn't look like recognizable OME-Zarr metadata at all.
    """
    zarr_json = path / "zarr.json"
    if zarr_json.exists():
        try:
            meta = json.loads(zarr_json.read_text())
            ome_version = meta.get("attributes", {}).get("ome", {}).get("version")
        except Exception:
            ome_version = None
        if ome_version:
            return f"OME-Zarr v{ome_version} (Zarr format 3)"
        return None

    zgroup = path / ".zgroup"
    if zgroup.exists():
        ome_version = None
        try:
            zattrs = json.loads((path / ".zattrs").read_text())
            multiscales = zattrs.get("multiscales") or []
            if multiscales:
                ome_version = multiscales[0].get("version")
        except Exception:
            ome_version = None
        if ome_version:
            return f"OME-Zarr v{ome_version} (Zarr format 2)"
        return "Zarr format 2 (pre-v0.5 OME-Zarr storage layout)"

    return None


def validate_ome_zarr(path: str | Path) -> None:
    """Validate ``path`` as an OME-Zarr v0.5 store; raise ``ValidationError`` on failure (FR-001).

    Raises ``ValidationError`` if the store is missing or invalid, or if the ``ome-zarr-models``
    dependency is unavailable.
    """
    path = Path(path)
    if not path.exists():
        raise ValidationError(f"input store does not exist: {path}")

    try:
        from ome_zarr_models import open_ome_zarr
        from ome_zarr_models.exceptions import ValidationWarning
    except ImportError as exc:  # broken/partial install (FR-005)
        raise ValidationError(_MISSING_DEP_HINT) from exc

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", category=ValidationWarning)
            open_ome_zarr(str(path), version="0.5")
    except Exception as exc:
        actual = _describe_actual_version(path)
        if actual is not None:
            raise ValidationError(
                f"input at {path} is {actual}, but ome-zarr-masker requires OME-Zarr v0.5 "
                "(Zarr format 3); convert the store to v0.5 before running this tool"
            ) from exc
        raise ValidationError(f"input is not a valid OME-Zarr v0.5 store: {exc}") from exc
