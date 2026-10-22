"""Enable ``python -m ome_zarr_masker``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
