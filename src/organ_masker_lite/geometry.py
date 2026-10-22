"""Physical nearest-pixel mapping between OME-Zarr pyramid levels.

A voxel index ``i`` on a level with scale ``s`` and translation ``t`` has its centre at the
physical position ``i * s + t`` (OME-Zarr ``coordinateTransformations``). Mapping a position from
one level to another and taking the nearest voxel centre handles both pyramid conventions in use:
half-pixel translations (``(scale_N - scale_0) / 2``, as written by ome-zarr-tools) and none.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

# Tolerance that makes floating-point near-ties (e.g. 6.5 computed as 6.5000000001) resolve like
# exact ties: to the lower index.
_TIE_TOLERANCE = 1e-9


def nearest_index(
    coords: npt.ArrayLike,
    from_scale: float,
    from_translation: float,
    to_scale: float,
    to_translation: float,
) -> np.ndarray:
    """Map voxel coordinates on one level to the nearest voxel index on another (one axis).

    Exact ties go to the lower index. The result is not clipped: callers decide whether an
    out-of-range index is clamped (index vectors) or rejected (prompt validation).
    """
    physical = np.asarray(coords, dtype=float) * from_scale + from_translation
    x = (physical - to_translation) / to_scale
    return np.ceil(x - 0.5 - _TIE_TOLERANCE).astype(np.int64)
