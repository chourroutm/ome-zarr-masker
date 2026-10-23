"""Where an OME-Zarr store lives: a local path or a remote URL (feature 010).

:meth:`StoreLocation.parse` turns every store argument into a :class:`StoreLocation` once, with no
network I/O (research R2): strings without ``<scheme>://`` stay local paths, handled exactly as
before; ``s3://``, ``gs://``, ``az://``, ``abfs://`` and HTTPS links on those providers' hosts
become object-store locations; any other ``http(s)://`` URL is generic, read-only HTTP.
:meth:`StoreLocation.open_store` gives what zarr opens: the path string for a local store, a
``zarr.storage.FsspecStore`` over the provider's filesystem for a remote one (research R1).

Provider packages are optional extras imported only when a URL of that provider is opened
(research R3). Credentials are ambient only, and URLs carrying credentials are rejected, so nothing
secret can reach a log, run record or error message (research R4). Provider errors are mapped to a
single :class:`RemoteStoreError` with a ``cause`` (research R6).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

#: Schemes treated as remote; any other ``<scheme>://`` is rejected (C-LOC-2).
SUPPORTED_SCHEMES = ("http", "https", "s3", "gs", "az", "abfs")

_READABLE_FORMS = (
    "s3://bucket/key, gs://bucket/key, az://container/path, "
    "abfs://container@account.dfs.core.windows.net/path, https:// links on S3, "
    "storage.googleapis.com or <account>.blob.core.windows.net hosts, or any other "
    "http(s):// URL (read-only)"
)
_WRITABLE_FORMS = (
    "s3://bucket/key, gs://bucket/key, az://container/path, "
    "abfs://container@account.dfs.core.windows.net/path, or https:// links on S3, "
    "storage.googleapis.com or <account>.blob.core.windows.net hosts"
)

#: Optional extra providing each remote kind's filesystem (research R3).
_EXTRAS = {"s3": "s3", "gcs": "gcs", "azure": "azure", "http": "http"}

#: Environment variables that configure Azure credentials; with none set (and no Azure CLI
#: login), Azure access is anonymous so public containers need no setup (research R4).
_AZURE_CREDENTIAL_VARS = (
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_STORAGE_ACCOUNT_KEY",
    "AZURE_STORAGE_SAS_TOKEN",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_TENANT_ID",
    "AZURE_FEDERATED_TOKEN_FILE",
)

_S3_PATH_HOST = re.compile(r"^s3(?:[.-](?P<region>[a-z0-9-]+))?\.amazonaws\.com$")
_S3_VIRTUAL_HOST = re.compile(
    r"^(?P<bucket>.+)\.s3(?:[.-](?P<region>[a-z0-9-]+))?\.amazonaws\.com$"
)
_GCS_HOST = "storage.googleapis.com"
_AZURE_BLOB_HOST = re.compile(r"^(?P<account>[a-z0-9]+)\.blob\.core\.windows\.net$")
_AZURE_DFS_HOST = re.compile(r"^(?P<account>[a-z0-9]+)\.(?:dfs|blob)\.core\.windows\.net$")
_SCHEME = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://")

#: Test hook: ``kind -> factory(location) -> async filesystem`` used instead of the provider's
#: (research R7). Empty in normal use.
_FILESYSTEM_OVERRIDE: dict[str, Callable[[StoreLocation], Any]] = {}


class RemoteStoreError(ValueError):
    """A remote store location is unsupported, unreachable, missing, forbidden or not writable.

    ``cause`` is one of ``not_found``, ``forbidden``, ``network``, ``unsupported``,
    ``not_writable``, ``missing_dependency`` or ``credentials_in_url``; ``location`` is the
    location's display form (never containing credentials). Distinct from OME-Zarr validation
    errors (FR-010).
    """

    def __init__(self, message: str, *, cause: str, location: str):
        super().__init__(message)
        self.cause = cause
        self.location = location


@dataclass(frozen=True)
class StoreLocation:
    """A parsed store argument (data-model.md). Build with :meth:`parse`."""

    raw: str
    kind: str  # "local" | "http" | "s3" | "gcs" | "azure"
    path: Path | None = None
    bucket: str | None = None
    key: str = ""
    host: str | None = None
    region: str | None = None
    account: str | None = None
    scheme: str | None = None  # http/https, for generic HTTP only

    # -- parsing --------------------------------------------------------------------------
    @classmethod
    def parse(cls, value: str | Path | StoreLocation) -> StoreLocation:
        """Classify ``value`` without any network I/O; raise :class:`RemoteStoreError` if bad."""
        if isinstance(value, StoreLocation):
            return value
        if isinstance(value, Path):
            return cls(raw=str(value), kind="local", path=value)
        raw = str(value)
        m = _SCHEME.match(raw)
        if m is None:
            return cls(raw=raw, kind="local", path=Path(raw))

        scheme = m.group("scheme").lower()
        parts = urlsplit(raw)
        redacted = _redact(scheme, parts)
        if scheme not in SUPPORTED_SCHEMES:
            raise RemoteStoreError(
                f"unsupported URL scheme '{scheme}://' in {redacted}; supported forms: "
                f"{_READABLE_FORMS}, or a local path",
                cause="unsupported",
                location=redacted,
            )
        _reject_credentials(scheme, parts, redacted)

        host = (parts.hostname or "").lower()
        segments = parts.path.strip("/")
        if scheme == "s3":
            return cls._object(raw, "s3", parts.netloc, segments, redacted)
        if scheme == "gs":
            return cls._object(raw, "gcs", parts.netloc, segments, redacted)
        if scheme == "az":
            account = _az_account()
            return cls._object(raw, "azure", parts.netloc, segments, redacted, account=account)
        if scheme == "abfs":
            container, _, _ = parts.netloc.partition("@")
            dfs = _AZURE_DFS_HOST.match(host)
            if dfs is None or not container:
                raise RemoteStoreError(
                    f"cannot read the container and account of {redacted}; expected "
                    "abfs://container@account.dfs.core.windows.net/path",
                    cause="unsupported",
                    location=redacted,
                )
            return cls._object(
                raw, "azure", container, segments, redacted, account=dfs.group("account")
            )

        # http(s): provider hosts first, then generic HTTP (spec Clarifications Q1-Q2)
        if (s3 := _S3_PATH_HOST.match(host)) is not None:
            bucket, _, key = segments.partition("/")
            return cls._object(raw, "s3", bucket, key, redacted, region=s3.group("region"))
        if (s3 := _S3_VIRTUAL_HOST.match(host)) is not None:
            return cls._object(
                raw, "s3", s3.group("bucket"), segments, redacted, region=s3.group("region")
            )
        if host == _GCS_HOST:
            bucket, _, key = segments.partition("/")
            return cls._object(raw, "gcs", bucket, key, redacted)
        if (az := _AZURE_BLOB_HOST.match(host)) is not None:
            container, _, key = segments.partition("/")
            return cls._object(raw, "azure", container, key, redacted, account=az.group("account"))
        if not host:
            raise RemoteStoreError(
                f"URL has no host: {redacted}", cause="unsupported", location=redacted
            )
        netloc = host if parts.port is None else f"{host}:{parts.port}"
        return cls(raw=raw, kind="http", host=netloc, key=parts.path.rstrip("/"), scheme=scheme)

    @classmethod
    def _object(cls, raw, kind, bucket, key, redacted, *, region=None, account=None):
        if not bucket:
            what = "container" if kind == "azure" else "bucket"
            raise RemoteStoreError(
                f"no {what} in {redacted}", cause="unsupported", location=redacted
            )
        return cls(
            raw=raw,
            kind=kind,
            bucket=bucket,
            key=key.strip("/"),
            region=region,
            account=account,
        )

    # -- derived ------------------------------------------------------------------------
    @property
    def is_remote(self) -> bool:
        return self.kind != "local"

    @property
    def writable(self) -> bool:
        """Generic HTTP(S) is read-only; everything else can be written (FR-003)."""
        return self.kind != "http"

    @property
    def display(self) -> str:
        """The form recorded in run records, logs and errors (FR-011; never holds credentials)."""
        if self.kind == "local":
            return self.raw
        if self.kind == "http":
            return f"{self.scheme}://{self.host}{self.key}"
        prefix = {"s3": "s3", "gcs": "gs", "azure": "az"}[self.kind]
        url = f"{prefix}://{self.bucket}/{self.key}" if self.key else f"{prefix}://{self.bucket}"
        return f"{url} (account {self.account})" if self.kind == "azure" else url

    def _identity(self) -> tuple:
        if self.kind == "local":
            return ("local", str(Path(self.path).resolve()))
        return (self.kind, self.account, self.host, self.bucket, self.key)

    def same_store(self, other: StoreLocation) -> bool:
        """Whether both locations name the same store, whatever URL form each used."""
        return self._identity() == other._identity()

    @property
    def fs_path(self) -> str:
        """The store's root as the provider filesystem names it."""
        if self.kind == "http":
            return self.display
        return f"{self.bucket}/{self.key}" if self.key else str(self.bucket)

    # -- opening ------------------------------------------------------------------------
    def open_store(self, read_only: bool = True):
        """What zarr opens: the path string (local, unchanged) or an ``FsspecStore`` (remote)."""
        if not read_only and not self.writable:
            raise RemoteStoreError(
                f"cannot write to {self.display}: plain HTTP(S) locations are read-only; "
                f"write to {_WRITABLE_FORMS}",
                cause="not_writable",
                location=self.display,
            )
        if self.kind == "local":
            return str(self.path)
        from zarr.storage import FsspecStore

        fs = filesystem_for(self)
        return FsspecStore(fs, path=self.fs_path, read_only=read_only)


def _redact(scheme: str, parts) -> str:
    """The URL without userinfo, query or fragment, for messages about a rejected URL."""
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    if scheme == "abfs" and "@" in parts.netloc:
        container = parts.netloc.split("@", 1)[0].split(":", 1)[0]
        host = f"{container}@{host}"
    return f"{scheme}://{host}{parts.path}"


def redact_url(value: str) -> str:
    """``value`` with any URL credentials, query or fragment removed; other strings unchanged.

    For logging an argument before it has been parsed (FR-011): a URL carrying credentials is
    rejected by :meth:`StoreLocation.parse`, but the invocation log records it first.
    """
    m = _SCHEME.match(value)
    if m is None:
        return value
    parts = urlsplit(value)
    if "@" not in parts.netloc and not parts.query and not parts.fragment:
        return value
    return _redact(m.group("scheme").lower(), parts)


def _reject_credentials(scheme: str, parts, redacted: str) -> None:
    """URLs with userinfo or a query string are refused (research R4, C-LOC-3)."""
    userinfo = parts.netloc.rpartition("@")[0] if "@" in parts.netloc else ""
    # abfs:// puts the container where userinfo would be; only a password-like part is secret
    has_secret = (":" in userinfo) if scheme == "abfs" else bool(userinfo)
    if has_secret or parts.query or parts.fragment:
        raise RemoteStoreError(
            f"{redacted}: URLs must not carry credentials or signed query parameters; configure "
            "access through the provider's standard credentials (environment, profile or config "
            "file, or the machine's cloud identity) instead",
            cause="credentials_in_url",
            location=redacted,
        )


def _az_account() -> str:
    """The Azure account for ``az://`` URLs, from standard Azure configuration."""
    account = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
    if account:
        return account
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    for item in conn.split(";"):
        name, _, value = item.partition("=")
        if name.strip().lower() == "accountname" and value.strip():
            return value.strip()
    raise RemoteStoreError(
        "az:// URLs need a storage account: set AZURE_STORAGE_ACCOUNT_NAME (or "
        "AZURE_STORAGE_CONNECTION_STRING), or use "
        "abfs://container@account.dfs.core.windows.net/path or "
        "https://account.blob.core.windows.net/container/path",
        cause="unsupported",
        location="az://",
    )


# -- provider filesystems (research R1, R3, R4) ---------------------------------------------


def _missing(location: StoreLocation, exc: ImportError) -> RemoteStoreError:
    extra = _EXTRAS[location.kind]
    return RemoteStoreError(
        f"opening {location.display} needs optional packages that are not installed ({exc}); "
        f'install them with: pip install "ome-zarr-masker[{extra}]" (or [remote] for all)',
        cause="missing_dependency",
        location=location.display,
    )


def _aws_credentials_available() -> bool:
    """Whether botocore's default chain resolves any credentials (env, profile, role...)."""
    try:
        import botocore.session

        return botocore.session.Session().get_credentials() is not None
    except Exception:  # noqa: BLE001 - treat a broken config as "no credentials"
        return False


def _azure_cli_logged_in() -> bool:
    return (Path.home() / ".azure" / "msal_token_cache.json").exists()


def filesystem_for(location: StoreLocation):
    """The async fsspec filesystem for a remote ``location``, with ambient credentials only."""
    override = _FILESYSTEM_OVERRIDE.get(location.kind)
    if override is not None:
        return override(location)
    kind = location.kind
    common = {"asynchronous": True, "skip_instance_cache": True}
    try:
        if kind == "s3":
            import s3fs

            kwargs = dict(common)
            if location.region:
                kwargs["client_kwargs"] = {"region_name": location.region}
            if not _aws_credentials_available():
                kwargs["anon"] = True  # public buckets need no setup (FR-005)
            return s3fs.S3FileSystem(**kwargs)
        if kind == "gcs":
            import gcsfs

            # token=None: application default credentials, else anonymous
            return gcsfs.GCSFileSystem(token=None, **common)
        if kind == "azure":
            import adlfs

            kwargs = dict(common, account_name=location.account)
            configured = any(os.environ.get(v) for v in _AZURE_CREDENTIAL_VARS)
            if not configured and not _azure_cli_logged_in():
                kwargs["anon"] = True
            return adlfs.AzureBlobFileSystem(**kwargs)
        if kind == "http":
            import aiohttp  # noqa: F401 - HTTPFileSystem needs it; fail with a clear extra name
            from fsspec.implementations import http

            # no credentials involved: share fsspec's cached instance (and its HTTP session)
            return http.HTTPFileSystem(asynchronous=True)
    except ImportError as exc:
        raise _missing(location, exc) from exc
    raise ValueError(f"no filesystem for a {kind} location")


# -- error mapping (research R6) ------------------------------------------------------------

_CAUSE_TEXT = {"not_found": "not found", "forbidden": "access denied", "network": "network error"}


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _status(exc: BaseException) -> int | None:
    for attr in ("status", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if isinstance(response, dict):  # botocore ClientError
        code = response.get("Error", {}).get("Code", "")
        if code in ("AccessDenied", "403", "Forbidden", "InvalidAccessKeyId"):
            return 403
        if code in ("NoSuchBucket", "NoSuchKey", "404", "NotFound"):
            return 404
    return None


def _classify(exc: BaseException) -> str | None:
    status = _status(exc)
    if status in (401, 403):
        return "forbidden"
    if status == 404:
        return "not_found"
    if isinstance(exc, FileNotFoundError):
        return "not_found"
    if isinstance(exc, PermissionError):
        return "forbidden"
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "network"
    if type(exc).__module__.split(".")[0] in ("aiohttp", "botocore", "aiobotocore"):
        return "network"
    return None


def map_remote_error(exc: BaseException, location: StoreLocation) -> RemoteStoreError | None:
    """A :class:`RemoteStoreError` for a provider failure, or ``None`` if ``exc`` isn't one."""
    for e in _chain(exc):
        if isinstance(e, RemoteStoreError):
            return e
        cause = _classify(e)
        if cause is not None:
            detail = " ".join(str(e).split())[:300] or type(e).__name__
            return RemoteStoreError(
                f"{location.display}: {_CAUSE_TEXT[cause]} ({detail})",
                cause=cause,
                location=location.display,
            )
    return None


@contextmanager
def remote_errors(location: StoreLocation) -> Iterator[None]:
    """Re-raise provider failures inside the block as :class:`RemoteStoreError`."""
    try:
        yield
    except RemoteStoreError:
        raise
    except Exception as exc:
        # this package's own errors (validation, reader...) already say what went wrong
        ours = type(exc).__module__.startswith("ome_zarr_masker.")
        mapped = map_remote_error(exc, location) if location.is_remote and not ours else None
        if mapped is None:
            raise
        raise mapped from exc


def read_key(store, key: str) -> bytes | None:
    """Read one object of an opened remote store synchronously; ``None`` if it doesn't exist."""
    from zarr.core.buffer import default_buffer_prototype
    from zarr.core.sync import sync

    buf = sync(store.get(key, prototype=default_buffer_prototype()))
    return None if buf is None else buf.to_bytes()
