"""Shared test fixtures: a synthetic OME-Zarr v0.5 volume."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import zarr
from ome_zarr_models.v05.axes import Axis
from ome_zarr_models.v05.image import Image
from pydantic_zarr.v3 import ArraySpec


def _spec(a: np.ndarray, chunks, shards) -> ArraySpec:
    if chunks is None:
        return ArraySpec.from_array(a, dimension_names=["z", "y", "x"])
    c = tuple(min(ci, s) for ci, s in zip(chunks, a.shape, strict=True))
    kw = {}
    if shards is not None:
        # a shard must be a whole multiple of the chunk, and need not exceed the array
        kw["shards"] = tuple(
            -(-min(si, s) // ci) * ci for si, s, ci in zip(shards, a.shape, c, strict=True)
        )
    template = zarr.create_array(
        store=zarr.storage.MemoryStore(),
        shape=a.shape,
        dtype=a.dtype,
        chunks=c,
        dimension_names=["z", "y", "x"],
        **kw,
    )
    return ArraySpec.from_zarr(template)


def write_ome_zarr(
    path: Path,
    level0: np.ndarray,
    n_levels: int = 2,
    axis_factors: tuple[int, int, int] = (2, 2, 2),
    *,
    chunks: tuple[int, int, int] | None = None,
    shards: tuple[int, int, int] | None = None,
    scales: list[list[float]] | None = None,
    translations: list[list[float] | None] | None = None,
) -> Path:
    """Write a minimal valid OME-Zarr v0.5 multiscale image (axes z, y, x).

    ``axis_factors`` is the per-axis (z, y, x) downsample factor between consecutive levels;
    the default ``(2, 2, 2)`` reproduces every pre-existing caller's isotropic pyramid exactly.
    Passing different factors per axis builds an anisotropic pyramid (feature
    008-level-agnostic-prompts, FR-004). ``chunks``/``shards`` store every level with that
    layout (capped to the level); ``scales``/``translations`` override the per-level transforms
    (feature 009-scalable-mask-writer). Defaults reproduce the original fixture exactly.
    """
    fz, fy, fx = axis_factors
    arrays = [level0]
    for _ in range(1, n_levels):
        arrays.append(arrays[-1][::fz, ::fy, ::fx].copy())
    axes = [Axis(name=n, type="space") for n in ("z", "y", "x")]
    specs = [_spec(a, chunks, shards) for a in arrays]
    image = Image.new(
        array_specs=specs,
        paths=[str(i) for i in range(n_levels)],
        axes=axes,
        scales=scales or [[float(f) ** i for f in axis_factors] for i in range(n_levels)],
        translations=translations or [None] * n_levels,
    )
    image.to_zarr(zarr.storage.LocalStore(str(path)), path="")
    for i, arr in enumerate(arrays):
        zarr.open_array(store=str(path), path=str(i), mode="r+")[:] = arr
    return path


def assert_ome_zarr_models_valid(path: Path) -> None:
    """Validate ``path`` with ome-zarr-models itself, independently of this project's wrapper.

    Runs the package's own ``ome-zarr-models validate`` CLI (installed next to this interpreter)
    and also opens the store in-process as OME-Zarr 0.5 with ``ValidationWarning`` promoted to
    an error, requiring a v0.5 ``Image`` back.
    """
    import subprocess
    import sys
    import warnings

    from ome_zarr_models import open_ome_zarr
    from ome_zarr_models.exceptions import ValidationWarning

    cli = Path(sys.executable).parent / "ome-zarr-models"
    proc = subprocess.run(
        [str(cli), "validate", str(path)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0 and "Valid OME-Zarr" in proc.stdout, proc.stdout + proc.stderr

    with warnings.catch_warnings():
        warnings.simplefilter("error", category=ValidationWarning)
        model = open_ome_zarr(str(path), version="0.5")
    assert isinstance(model, Image), type(model)


@pytest.fixture
def single_blob_zarr(tmp_path):
    """A volume with one bright cuboid blob; returns (path, blob_center_xy, frame_index)."""
    vol = np.zeros((8, 16, 16), dtype=np.uint8)
    vol[2:6, 4:12, 4:12] = 200
    path = write_ome_zarr(tmp_path / "input.ome.zarr", vol)
    # center of the blob on frame z=4: (x, y) = (8, 8)
    return path, (8.0, 8.0), 4


@pytest.fixture
def two_blob_zarr(tmp_path):
    """A volume with two separate blobs; returns (path, blobA_xy, blobB_xy, frame_index)."""
    vol = np.zeros((8, 24, 24), dtype=np.uint8)
    vol[2:6, 3:9, 3:9] = 200  # blob A
    vol[2:6, 15:21, 15:21] = 200  # blob B (separate)
    path = write_ome_zarr(tmp_path / "two.ome.zarr", vol)
    return path, (6.0, 6.0), (18.0, 18.0), 4


@pytest.fixture(autouse=True)
def isolate_logs(tmp_path, monkeypatch):
    """Redirect per-invocation input logs (feature 002) to a temp dir, never the repo cwd."""
    monkeypatch.setenv("OME_ZARR_MASKER_LOG_DIR", str(tmp_path / "_logs"))


def sam2_available() -> bool:
    """True only if the real SAM2 backend can actually be constructed.

    Used by ``real_backend`` skip guards. This attempts construction rather than checking
    ``importlib.util.find_spec("sam2")``, because a module merely *named* like the backend may be
    discoverable on the path yet not provide the real predictor (a partial install, etc.).
    Construction performs the same deferred ``torch``/``sam2`` import the backend uses and raises
    ``ImportError`` when the dependency is genuinely unusable, so the guard skips rather than
    hard-failing in that case.
    """
    from ome_zarr_masker.sam2 import Sam2Backend

    try:
        Sam2Backend()
    except ImportError:
        return False
    return True


# -- remote stores (feature 010) ------------------------------------------------------------


class _RangeHandler:
    """Factory for a static-file handler with HTTP Range support that counts body bytes served."""

    @staticmethod
    def make(root: Path, counter: dict):
        from http.server import SimpleHTTPRequestHandler

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(root), **kwargs)

            def log_message(self, *args):  # keep test output quiet
                pass

            def _target(self) -> Path | None:
                p = Path(self.translate_path(self.path))
                return p if p.is_file() else None

            def do_HEAD(self):  # noqa: N802
                p = self._target()
                if p is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(p.stat().st_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

            def do_GET(self):  # noqa: N802
                p = self._target()
                if p is None:
                    self.send_error(404)
                    return
                data = p.read_bytes()
                rng = self.headers.get("Range")
                status = 200
                if rng and rng.startswith("bytes="):
                    start_s, _, end_s = rng[6:].partition("-")
                    if start_s == "":
                        start, end = max(0, len(data) - int(end_s)), len(data) - 1
                    else:
                        start = int(start_s)
                        end = int(end_s) if end_s else len(data) - 1
                    end = min(end, len(data) - 1)
                    body = data[start : end + 1]
                    status = 206
                else:
                    body = data
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Accept-Ranges", "bytes")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                self.end_headers()
                self.wfile.write(body)
                counter["bytes"] += len(body)
                counter["requests"].append(self.path)

        return Handler


class HttpStoreServer:
    """A local HTTP server over ``root``; ``url(rel)`` names a served path."""

    def __init__(self, root: Path):
        import threading
        from http.server import ThreadingHTTPServer

        self.root = root
        self.counter = {"bytes": 0, "requests": []}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler.make(root, self.counter))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.base = f"http://127.0.0.1:{self._server.server_address[1]}"
        self.running = True

    def url(self, rel: str) -> str:
        return f"{self.base}/{rel}"

    @property
    def bytes_served(self) -> int:
        return self.counter["bytes"]

    def reset_counter(self) -> None:
        self.counter["bytes"] = 0
        self.counter["requests"].clear()

    def stop(self) -> None:
        if self.running:
            self._server.shutdown()
            self._server.server_close()
            self.running = False


@pytest.fixture
def http_store_server(tmp_path):
    """Serve ``tmp_path / "served"`` over HTTP (Range-capable, byte-counting)."""
    root = tmp_path / "served"
    root.mkdir()
    server = HttpStoreServer(root)
    yield server
    server.stop()


def upload_dir_to_s3(local: Path, bucket: str, prefix: str, *, public: bool = False) -> None:
    """Copy a local store directory to ``s3://bucket/prefix`` (the moto server from ``moto_s3``).

    ``public`` uploads every object with a public-read ACL, readable without credentials.
    """
    import boto3

    client = boto3.client("s3")
    extra = {"ACL": "public-read"} if public else {}
    for f in sorted(p for p in local.rglob("*") if p.is_file()):
        key = f"{prefix}/{f.relative_to(local).as_posix()}"
        client.put_object(Bucket=bucket, Key=key, Body=f.read_bytes(), **extra)


def download_s3_dir(bucket: str, prefix: str, local: Path) -> Path:
    """Copy every object under ``s3://bucket/prefix`` into ``local`` (to validate/compare it)."""
    import boto3

    client = boto3.client("s3")
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix + "/")
    for page in pages:
        for obj in page.get("Contents", []):
            dest = local / obj["Key"][len(prefix) + 1 :]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(client.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read())
    return local


@pytest.fixture
def moto_s3(monkeypatch):
    """An in-process moto S3 server with test credentials; yields its endpoint URL."""
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    monkeypatch.setenv("AWS_ENDPOINT_URL", endpoint)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    yield endpoint
    server.stop()


class FailingMemoryFileSystem:
    """Factory for an in-memory filesystem whose writes fail after ``fail_after`` puts."""

    @staticmethod
    def make(fail_after: int | None, log: list):
        from fsspec.implementations.memory import MemoryFileSystem

        class Failing(MemoryFileSystem):
            def pipe_file(self, path, value, *args, **kwargs):
                if fail_after is not None and len(log) >= fail_after:
                    raise OSError(f"injected failure writing {path}")
                log.append(path)
                return super().pipe_file(path, value, *args, **kwargs)

        Failing.store = {}  # a store of its own, not shared with other MemoryFileSystem uses
        Failing.pseudo_dirs = [""]
        return Failing


@pytest.fixture
def memory_fs(monkeypatch):
    """Route ``s3://`` locations to an in-memory filesystem; ``memory_fs.fail_after(n)`` injects
    a write failure after ``n`` puts. Yields a controller with ``fs`` (sync) and ``puts`` (log)."""
    from fsspec.implementations.asyn_wrapper import AsyncFileSystemWrapper

    from ome_zarr_masker.io import location as loc_mod

    class Controller:
        def __init__(self):
            self.puts: list[str] = []
            self.fail_after(None)

        def fail_after(self, n: int | None) -> None:
            store = getattr(self, "fs", None)
            cls = FailingMemoryFileSystem.make(n, self.puts)
            if store is not None:
                cls.store = type(store).store  # keep the contents across failure settings
                cls.pseudo_dirs = type(store).pseudo_dirs
            self.fs = cls(skip_instance_cache=True)

    ctl = Controller()
    monkeypatch.setitem(
        loc_mod._FILESYSTEM_OVERRIDE,
        "s3",
        lambda location: AsyncFileSystemWrapper(ctl.fs, asynchronous=True),
    )
    return ctl


def live_url(provider: str) -> str | None:
    """The opt-in live test prefix for ``provider`` (S3, GCS or AZURE), if configured."""
    import os

    return os.environ.get(f"OME_ZARR_MASKER_TEST_{provider}_URL") or None


class StubBackend:
    """Deterministic stand-in for SAM2: foreground wherever the frame is bright.

    Used by remote-store tests, which check I/O equivalence, not segmentation quality.
    """

    def segment_video(self, frames: np.ndarray, prompts) -> np.ndarray:
        gray = frames[..., 0] if frames.ndim == 4 else frames
        return gray > 100
