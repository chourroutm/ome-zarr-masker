"""Run configuration (including the post-processing steps) and model-directory resolution."""

from __future__ import annotations

import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .postprocess.steps import PostProcessSpec, ResolvedStep, parse_steps

DEFAULT_MODEL_DIR = "ome_zarr_masker_models"
MODEL_DIR_ENV = "OME_ZARR_MASKER_MODEL_DIR"

#: A weight fetcher: download the file at ``url`` to the local path ``dest``. Injectable so the
#: resolution logic can be tested without touching the network (see ``RunConfig.resolve_weight``).
WeightDownloader = Callable[[str, Path], None]


def default_weight_downloader(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest`` atomically via a temporary ``.part`` file (FR-020)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 (trusted, operator-configured weight URL)
    tmp.replace(dest)


DEFAULT_LOG_DIR = "ome_zarr_masker_logs"
LOG_DIR_ENV = "OME_ZARR_MASKER_LOG_DIR"

#: Sentinel meaning "use the coarsest level (highest index)".
COARSEST_LEVEL = -1


@dataclass
class LogConfig:
    """Configuration for per-invocation input logging (feature 002, FR-007)."""

    log_dir: Path | None = None
    level: str = "INFO"
    enabled: bool = True

    def resolved_log_dir(self) -> Path:
        """Resolve the log directory: explicit > env var > default (cwd subdir) (FR-007)."""
        if self.log_dir is not None:
            return Path(self.log_dir)
        env = os.environ.get(LOG_DIR_ENV)
        if env:
            return Path(env)
        return Path.cwd() / DEFAULT_LOG_DIR


@dataclass
class RunConfig:
    """The complete, reproducible parameterization of a masking run (FR-014)."""

    level: int = COARSEST_LEVEL
    axes: list[str] = field(default_factory=lambda: ["z"])
    direction: str = "forward"
    combine_rule: str = "majority"
    #: Ordered post-processing (feature 011); ``default`` inherits the prompt file's saved steps.
    postprocess: PostProcessSpec = field(default_factory=lambda: parse_steps("default"))
    model_dir: Path | None = None
    allow_download: bool = True
    overwrite: bool = False
    frame_range: tuple[int, int] | None = None
    #: ``postprocess`` resolved for the run level (set by the pipeline before segmentation).
    resolved_postprocess: tuple[ResolvedStep, ...] | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        # ``level`` is either the COARSEST sentinel or a concrete non-negative index (FR-003).
        if self.level != COARSEST_LEVEL and self.level < 0:
            raise ValueError(
                f"invalid level {self.level}; use a non-negative index or "
                f"{COARSEST_LEVEL} for the coarsest (default) level"
            )
        if self.frame_range is not None:
            start, end = self.frame_range
            if start < 0 or end < start:
                raise ValueError(
                    f"invalid frame_range {self.frame_range}; expected 0 <= start <= end"
                )

    def resolved_model_dir(self) -> Path:
        """Resolve the model directory: explicit > env var > default (cwd subdir) (FR-019)."""
        if self.model_dir is not None:
            return Path(self.model_dir)
        env = os.environ.get(MODEL_DIR_ENV)
        if env:
            return Path(env)
        return Path.cwd() / DEFAULT_MODEL_DIR

    def resolve_weight(
        self,
        filename: str,
        url: str,
        *,
        description: str = "weights",
        downloader: WeightDownloader | None = None,
    ) -> Path:
        """Resolve a weight file, auto-downloading it on first use unless disabled (FR-019/020).

        ``filename`` is used as-is if absolute, otherwise resolved under
        :meth:`resolved_model_dir`. If the file already exists it is used as-is (no download). When
        it is absent and downloads are allowed, it is fetched from ``url`` via ``downloader`` (the
        injectable seam; defaults to :func:`default_weight_downloader`). When downloads are disabled
        (``allow_download=False``) and the file is missing, a clear :class:`FileNotFoundError`
        naming ``description`` is raised rather than reaching for the network.
        """
        path = Path(filename)
        if not path.is_absolute():
            path = self.resolved_model_dir() / filename
        if path.exists():
            return path
        if not self.allow_download:
            raise FileNotFoundError(
                f"{description} not found at {path} and downloads are disabled "
                f"(--no-download); place the file there or allow downloads."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        (downloader or default_weight_downloader)(url, path)
        return path

    def _postprocess_record(self) -> dict:
        """The steps in order and their source (feature 011, FR-012): resolved radii once known."""
        if self.resolved_postprocess is not None:
            steps = [s.to_record() for s in self.resolved_postprocess]
        else:
            steps = [ResolvedStep(s).to_record() for s in self.postprocess.steps or ()]
            for rec, s in zip(steps, self.postprocess.steps or (), strict=True):
                rec["radius"] = None if s.radius is None else s.radius.text
        return {"source": self.postprocess.source, "steps": steps}

    def to_record(self) -> dict:
        """Serialize the configuration for the reproducibility run-record (FR-014)."""
        return {
            "backend": "sam2",  # constant: SAM2 is the only segmentation backend
            "level": self.level,
            "axes": list(self.axes),
            "direction": self.direction,
            "combine_rule": self.combine_rule,
            "postprocess": self._postprocess_record(),
            "model_dir": str(self.resolved_model_dir()),
            "allow_download": self.allow_download,
            "frame_range": list(self.frame_range) if self.frame_range is not None else None,
        }
