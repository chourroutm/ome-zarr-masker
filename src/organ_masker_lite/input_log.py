"""Per-invocation input logging (feature 002).

Named ``input_log`` (not ``logging``) to avoid shadowing the stdlib package. Each invocation -- CLI
or API -- writes one plain-text log file ``<log_dir>/<run_id>.log`` capturing the command, parsed
arguments, resolved effective configuration, and the full prompt set, plus a final outcome line.
Logging is best-effort: a write failure emits a single stderr warning and never interrupts the
masking run, and nothing is ever written to stdout (FR-008, FR-009).
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .config import LogConfig

if TYPE_CHECKING:
    from .prompts.model import PromptSet


def generate_run_id() -> str:
    """A unique, time-sortable run id: ``<UTC-timestamp>-<short-uuid>`` (research R2).

    The fixed-width UTC timestamp gives chronological sort order; the 12-hex-char random suffix
    keeps ids distinct even for invocations that land in the same second.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:12]}"


class InvocationLog:
    """Writes one plain-text input-log file for a single invocation (best-effort)."""

    def __init__(self, run_id: str, command: str, config: LogConfig, arguments: dict | None = None):
        self.run_id = run_id
        self._command = command
        self._config = config
        self._arguments = arguments or {}
        self._handle = None
        self._disabled = False
        self._outcome = ("succeeded", "")
        self.path: Path | None = None

    # -- lifecycle --------------------------------------------------------
    def open(self) -> None:
        """Create the log file and write the header + invocation block (best-effort)."""
        if not self._config.enabled:
            self._disabled = True
            return
        try:
            log_dir = self._config.resolved_log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            self.path = log_dir / f"{self.run_id}.log"
            self._handle = open(self.path, "w", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - best-effort; degrade to a warning
            self._degrade(exc)
            return
        self._emit(f"run_id: {self.run_id}")
        self._emit(f"timestamp: {datetime.now(UTC).isoformat()}")
        self._emit(f"command: {self._command}")
        if self._arguments:
            self._emit("arguments:")
            for key in sorted(self._arguments):
                self._emit(f"  {key}: {self._arguments[key]}")

    def record_config(self, effective_config: dict) -> None:
        """Append the resolved effective configuration block (FR-001)."""
        self._emit("effective_config:")
        _emit_mapping(self._emit, effective_config, indent="  ")

    def record_write_level(self, layout, n_shards: int, workers: int, workers_source: str) -> None:
        """Append how one output level is written (feature 009, FR-012): layout and worker count."""
        self._emit(
            f"write_level: {layout.level} shape={tuple(layout.shape)} "
            f"chunks={tuple(layout.chunks)} "
            f"shards={tuple(layout.shards)} shards_total={n_shards} "
            f"workers={workers} ({workers_source}) source={layout.source}"
        )

    def record_prompts(self, prompts: PromptSet, source: str) -> None:
        """Append the full prompt set with its source, authoring level, and count (FR-003, FR-010;
        the authoring level is feature 008-level-agnostic-prompts, FR-002).
        """
        record = prompts.to_record()
        records = record["objects"]
        self._emit(f"prompt_source: {source}")
        self._emit(f"prompt_level: {record['level']}")
        self._emit(f"prompt_count: {len(records)}")
        self._emit("prompts:")
        for i, rec in enumerate(records):
            self._emit(f"  [{i}] obj_id={rec['obj_id']} frame_index={rec['frame_index']}")
            for pt in rec["points"]:
                self._emit(f"      point xy={pt['xy']} label={pt['label']}")
            if rec["box"] is not None:
                self._emit(f"      box xyxy={rec['box']}")

    def mark_failed(self, summary: str) -> None:
        """Record a failed outcome (the file is still written, FR-002)."""
        self._outcome = ("failed", summary)

    def finish(self) -> None:
        """Append the outcome line and close the file (best-effort)."""
        status, summary = self._outcome
        line = f"outcome: {status}" + (f" - {summary}" if summary else "")
        self._emit(line)
        if self._handle is not None:
            try:
                self._handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._handle = None

    # -- internals --------------------------------------------------------
    def _emit(self, text: str) -> None:
        if self._handle is None:
            return
        try:
            self._handle.write(text + "\n")
            self._handle.flush()
        except Exception as exc:  # noqa: BLE001 - degrade mid-write
            self._degrade(exc)

    def _degrade(self, exc: Exception) -> None:
        self._handle = None
        if not self._disabled:
            self._disabled = True
            print(f"warning: input logging disabled ({exc})", file=sys.stderr)


def _emit_mapping(emit, mapping: dict, indent: str) -> None:
    for key in mapping:
        value = mapping[key]
        if isinstance(value, dict):
            emit(f"{indent}{key}:")
            _emit_mapping(emit, value, indent + "  ")
        else:
            emit(f"{indent}{key}: {value}")


@contextmanager
def log_invocation(
    command: str, config: LogConfig, arguments: dict | None = None
) -> Iterator[InvocationLog]:
    """Open an :class:`InvocationLog`, yield it, and always write the outcome on exit.

    Inputs are recorded on entry (before validation) so a log exists even when the run fails before
    producing output (FR-002). If the body raises, the outcome is marked failed and the exception
    re-raised for the caller to handle.
    """
    log = InvocationLog(generate_run_id(), command, config, arguments)
    log.open()
    try:
        yield log
    except BaseException as exc:
        log.mark_failed(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        log.finish()


__all__ = ["generate_run_id", "InvocationLog", "log_invocation"]
