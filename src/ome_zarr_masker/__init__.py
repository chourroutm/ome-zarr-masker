"""ome-zarr-masker: mask organs in OME-Zarr v0.5 volumes with SAM2."""

from .api import MaskResult, OrganMaskPredictor
from .config import RunConfig

__version__ = "0.0.1"

__all__ = [
    "OrganMaskPredictor",
    "MaskResult",
    "RunConfig",
    "__version__",
]
