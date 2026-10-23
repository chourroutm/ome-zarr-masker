"""One-shot command-line interface (FR-008)."""

from __future__ import annotations

import argparse
import sys

from .config import COARSEST_LEVEL, LogConfig, PostProcessConfig, RunConfig
from .prompts.model import PromptError, load_prompt_file

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_INPUT_HELP = (
    "Path or URL (http(s)://, s3://, gs://, az://, abfs://) of the input OME-Zarr v0.5 store"
)
_OUTPUT_HELP = (
    "Path or URL (s3://, gs://, az://, abfs://, or an https:// link on those providers' hosts) "
    "of the output OME-Zarr v0.5 store"
)


def _add_log_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Directory for per-invocation log files (default: ./ome_zarr_masker_logs)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=_LOG_LEVELS,
        help="Logging verbosity (default: INFO)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ome-zarr-masker")
    sub = parser.add_subparsers(dest="command", required=True)

    mask = sub.add_parser("mask", help="Mask a structure in an OME-Zarr v0.5 volume.")
    mask.add_argument("input", help=_INPUT_HELP)
    mask.add_argument("output", help=_OUTPUT_HELP)
    mask.add_argument("--prompts", required=True, help="Prompt file (JSON)")
    mask.add_argument(
        "--level",
        type=int,
        default=COARSEST_LEVEL,
        help="Multiscale level to run on (default: coarsest)",
    )
    mask.add_argument(
        "--axes",
        default="z",
        help="Comma-separated sweep axes; the first is the prompted axis (default: z)",
    )
    mask.add_argument(
        "--direction",
        default="forward",
        choices=("forward", "forward_reverse"),
        help="Propagation mode (default: forward)",
    )
    mask.add_argument(
        "--combine",
        default="majority",
        choices=("majority", "union", "intersection"),
        help="Consensus rule when combining sweeps (default: majority)",
    )
    mask.add_argument(
        "--fill-holes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fill interior holes in the mask (default: on; use --no-fill-holes to disable)",
    )
    mask.add_argument(
        "--dilate",
        type=int,
        default=0,
        dest="dilation_radius",
        help="Dilation radius in voxels (default: 0)",
    )
    mask.add_argument(
        "--erode",
        type=int,
        default=0,
        dest="erosion_radius",
        help="Erosion radius in voxels (default: 0)",
    )
    mask.add_argument(
        "--invert",
        action="store_true",
        help="Swap the output mask's values: background becomes 1, organ becomes 0 (default: off)",
    )
    mask.add_argument("--overwrite", action="store_true", help="Overwrite an existing output")
    mask.add_argument(
        "--workers",
        type=_positive_int,
        default=None,
        help=(
            "Output shards written in parallel (default: as many as fit in an 8 GiB write "
            "budget, at most the CPU count). Peak write memory grows with this number."
        ),
    )
    mask.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    _add_log_options(mask)
    mask.set_defaults(func=_cmd_mask)

    interactive = sub.add_parser(
        "interactive", help="Open a napari session to place landmarks and export a mask."
    )
    interactive.add_argument("input", help=_INPUT_HELP)
    interactive.add_argument(
        "--level", type=int, default=COARSEST_LEVEL, help="Multiscale level (default: coarsest)"
    )
    interactive.add_argument("--model-dir", default=None, help="Weights directory override")
    interactive.add_argument(
        "--no-download",
        action="store_false",
        dest="allow_download",
        help="Disable weight auto-download",
    )
    interactive.set_defaults(func=_cmd_interactive)
    return parser


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be an integer >= 1, got {value!r}")
    return n


def _loggable_args(args: argparse.Namespace) -> dict:
    """Parsed arguments for the log, excluding internals (func, captured command line).

    String values have URL credentials removed (FR-011): the log is written before a URL that
    carries them is rejected.
    """
    from .io.location import redact_url

    return {
        k: redact_url(v) if isinstance(v, str) else v
        for k, v in vars(args).items()
        if k != "func" and not k.startswith("_")
    }


def _cmd_mask(args: argparse.Namespace) -> int:
    # Import the pipeline lazily so `--help` and arg parsing stay fast and dependency-light.
    from .engine.pipeline import PipelineError, run_masking
    from .input_log import log_invocation
    from .io.location import RemoteStoreError
    from .io.reader import ReaderError
    from .io.validate import ValidationError
    from .io.writer import WriterError

    log_config = LogConfig(log_dir=args.log_dir, level=args.log_level)
    command = getattr(args, "_command_line", "ome-zarr-masker mask")
    with log_invocation(command, log_config, arguments=_loggable_args(args)) as log:
        try:
            prompts = load_prompt_file(args.prompts)
        except (PromptError, FileNotFoundError, ValueError) as exc:
            log.mark_failed(str(exc))
            print(f"error: invalid prompt file: {exc}", file=sys.stderr)
            return 1

        try:
            config = RunConfig(
                level=args.level,
                axes=[a.strip() for a in args.axes.split(",") if a.strip()],
                direction=args.direction,
                combine_rule=args.combine,
                postprocess=PostProcessConfig(
                    fill_holes=args.fill_holes,
                    dilation_radius=args.dilation_radius,
                    erosion_radius=args.erosion_radius,
                    invert=args.invert,
                ),
                overwrite=args.overwrite,
            )
        except ValueError as exc:
            log.mark_failed(str(exc))
            print(f"error: {exc}", file=sys.stderr)
            return 1

        log.record_config(config.to_record())
        log.record_prompts(prompts, source=args.prompts)
        progress = (
            (lambda m: print(f"[ome-zarr-masker] {m}", file=sys.stderr)) if args.verbose else None
        )

        try:
            out = run_masking(
                args.input,
                args.output,
                prompts,
                config,
                progress=progress,
                run_id=log.run_id,
                workers=args.workers,
                on_level=log.record_write_level,
            )
        except (
            ValidationError,
            ReaderError,
            WriterError,
            PromptError,
            PipelineError,
            RemoteStoreError,
        ) as exc:
            log.mark_failed(str(exc))
            print(f"error: {exc}", file=sys.stderr)
            return 1

        print(str(out))
        return 0


def _cmd_interactive(args: argparse.Namespace) -> int:
    from .interactive import InteractiveSession
    from .io.reader import ReaderError
    from .io.validate import ValidationError

    try:
        session = InteractiveSession(
            args.input,
            level=args.level,
            model_dir=args.model_dir,
            allow_download=args.allow_download,
        )
        session.launch()
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (ValidationError, ReaderError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    effective_argv = argv if argv is not None else sys.argv[1:]
    from .io.location import redact_url

    args._command_line = "ome-zarr-masker " + " ".join(redact_url(str(a)) for a in effective_argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
