"""Store-location parsing, classification and provider options (feature 010, T003-T004).

Covers contracts/store-location.md C-LOC-1…6 and research R2/R4/R6 without any network access:
provider filesystem classes are replaced by recorders that capture their constructor arguments.
"""

from __future__ import annotations

import builtins
import subprocess
import sys
from pathlib import Path

import pytest

from ome_zarr_masker.io import location as loc_mod
from ome_zarr_masker.io.location import RemoteStoreError, StoreLocation

# -- accepted forms (C-LOC-1, C-LOC-4) -------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "kind", "bucket", "key", "region"),
    [
        ("s3://bkt/a/vol.ome.zarr", "s3", "bkt", "a/vol.ome.zarr", None),
        ("https://bkt.s3.amazonaws.com/a/vol.ome.zarr", "s3", "bkt", "a/vol.ome.zarr", None),
        ("https://bkt.s3.us-east-1.amazonaws.com/a/vol.ome.zarr", "s3", "bkt", "a/vol.ome.zarr",
         "us-east-1"),
        ("https://s3.eu-west-1.amazonaws.com/bkt/a/vol.ome.zarr", "s3", "bkt", "a/vol.ome.zarr",
         "eu-west-1"),
        ("https://s3.amazonaws.com/bkt/a/vol.ome.zarr", "s3", "bkt", "a/vol.ome.zarr", None),
        ("gs://bkt/a/vol.ome.zarr", "gcs", "bkt", "a/vol.ome.zarr", None),
        ("https://storage.googleapis.com/bkt/a/vol.ome.zarr", "gcs", "bkt", "a/vol.ome.zarr",
         None),
    ],
)  # fmt: skip
def test_s3_and_gcs_forms(url, kind, bucket, key, region):
    loc = StoreLocation.parse(url)
    assert (loc.kind, loc.bucket, loc.key, loc.region) == (kind, bucket, key, region)
    assert loc.is_remote and loc.writable
    assert loc.raw == url


def test_azure_forms(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "acct")
    forms = [
        "az://cont/a/vol.ome.zarr",
        "abfs://cont@acct.dfs.core.windows.net/a/vol.ome.zarr",
        "https://acct.blob.core.windows.net/cont/a/vol.ome.zarr",
    ]
    parsed = [StoreLocation.parse(f) for f in forms]
    for loc in parsed:
        assert (loc.kind, loc.account, loc.bucket, loc.key) == (
            "azure",
            "acct",
            "cont",
            "a/vol.ome.zarr",
        )
        assert loc.writable
        assert loc.display == "az://cont/a/vol.ome.zarr (account acct)"
    assert parsed[0].same_store(parsed[1]) and parsed[1].same_store(parsed[2])


def test_abfs_account_comes_from_host_not_environment(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "other")
    loc = StoreLocation.parse("abfs://cont@acct.dfs.core.windows.net/x")
    assert loc.account == "acct"


def test_az_account_from_connection_string(monkeypatch):
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_NAME", raising=False)
    monkeypatch.setenv(
        "AZURE_STORAGE_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=fromconn;AccountKey=c2VjcmV0;",
    )
    assert StoreLocation.parse("az://cont/x").account == "fromconn"


def test_https_forms_equal_scheme_forms():
    """C-LOC-4: each provider HTTPS form is the same store as its scheme form."""
    assert StoreLocation.parse("https://b.s3.us-east-1.amazonaws.com/k").same_store(
        StoreLocation.parse("s3://b/k")
    )
    assert StoreLocation.parse("https://s3.us-east-1.amazonaws.com/b/k/").same_store(
        StoreLocation.parse("s3://b/k")
    )
    assert StoreLocation.parse("https://storage.googleapis.com/b/k").same_store(
        StoreLocation.parse("gs://b/k")
    )
    assert not StoreLocation.parse("s3://b/k").same_store(StoreLocation.parse("gs://b/k"))
    assert not StoreLocation.parse("s3://b/k").same_store(StoreLocation.parse("s3://b/k2"))


def test_trailing_slash_and_host_case():
    # a virtual-hosted bucket is part of the (case-insensitive) host; the key keeps its case
    a = StoreLocation.parse("https://B.S3.AMAZONAWS.COM/Key/")
    assert (a.kind, a.bucket, a.key) == ("s3", "b", "Key")
    assert StoreLocation.parse("https://S3.AMAZONAWS.COM/Bkt/Key").bucket == "Bkt"
    h = StoreLocation.parse("HTTPS://Example.ORG/data/vol.ome.zarr/")
    assert h.kind == "http" and h.host == "example.org"
    assert h.display == "https://example.org/data/vol.ome.zarr"


def test_display_forms():
    assert StoreLocation.parse("https://b.s3.amazonaws.com/k").display == "s3://b/k"
    assert StoreLocation.parse("https://storage.googleapis.com/b/k").display == "gs://b/k"
    assert StoreLocation.parse("out.ome.zarr").display == "out.ome.zarr"


def test_generic_http_is_read_only():
    loc = StoreLocation.parse("https://example.org/data/vol.ome.zarr")
    assert loc.kind == "http" and loc.is_remote and not loc.writable
    assert StoreLocation.parse("http://localhost:8000/x").kind == "http"


@pytest.mark.parametrize(
    "value",
    ["out.ome.zarr", "./s3:data/x.ome.zarr", "/abs/path/x.ome.zarr", "rel/dir/", "s3:bucket"],
)
def test_local_strings_stay_local(value):
    """C-LOC-1: anything without ``<scheme>://`` is a local path, exactly as before."""
    loc = StoreLocation.parse(value)
    assert loc.kind == "local" and not loc.is_remote and loc.writable
    assert loc.path == Path(value)
    assert loc.display == value


def test_path_objects_are_local(tmp_path):
    loc = StoreLocation.parse(tmp_path / "x.ome.zarr")
    assert loc.kind == "local" and loc.path == tmp_path / "x.ome.zarr"
    assert loc.open_store(read_only=True) == str(tmp_path / "x.ome.zarr")


def test_local_same_store_uses_resolved_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    here = StoreLocation.parse("x.ome.zarr")
    assert here.same_store(StoreLocation.parse(tmp_path / "x.ome.zarr"))


# -- rejections (C-LOC-2, C-LOC-3, C-LOC-5) ---------------------------------------------------


@pytest.mark.parametrize("url", ["ftp://h/x", "file:///tmp/x", "gcs://b/k", "sftp://h/x"])
def test_unsupported_scheme(url):
    with pytest.raises(RemoteStoreError) as exc:
        StoreLocation.parse(url)
    assert exc.value.cause == "unsupported"
    for scheme in ("s3://", "gs://", "az://", "abfs://", "https://"):
        assert scheme in str(exc.value)


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        ("https://user:pw123@example.org/x", "pw123"),
        ("https://tok3n@example.org/x", "tok3n"),
        ("s3://b/k?sig=abc123", "abc123"),
        ("https://acct.blob.core.windows.net/c/x?sv=2020&sig=zzz999", "zzz999"),
        ("abfs://cont:k3y@acct.dfs.core.windows.net/x", "k3y"),
    ],
)
def test_credentials_in_url_rejected_without_echoing_them(url, secret):
    with pytest.raises(RemoteStoreError) as exc:
        StoreLocation.parse(url)
    assert exc.value.cause == "credentials_in_url"
    assert secret not in str(exc.value)
    assert secret not in exc.value.location


def test_az_without_account_rejected(monkeypatch):
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_NAME", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    with pytest.raises(RemoteStoreError) as exc:
        StoreLocation.parse("az://cont/x")
    assert exc.value.cause == "unsupported"
    assert "AZURE_STORAGE_ACCOUNT_NAME" in str(exc.value)


@pytest.mark.parametrize("url", ["s3:///k", "gs://", "https://s3.amazonaws.com/"])
def test_empty_bucket_rejected(url):
    with pytest.raises(RemoteStoreError) as exc:
        StoreLocation.parse(url)
    assert exc.value.cause == "unsupported"


def test_generic_http_not_writable():
    """C-LOC-5: opening generic HTTP(S) for writing fails, naming the writable forms."""
    loc = StoreLocation.parse("https://example.org/m.ome.zarr")
    with pytest.raises(RemoteStoreError) as exc:
        loc.open_store(read_only=False)
    assert exc.value.cause == "not_writable"
    assert "s3://" in str(exc.value) and "gs://" in str(exc.value) and "az://" in str(exc.value)


@pytest.mark.parametrize(
    ("url", "module", "extra"),
    [
        ("s3://b/k", "s3fs", "s3"),
        ("gs://b/k", "gcsfs", "gcs"),
        ("https://acct.blob.core.windows.net/c/k", "adlfs", "azure"),
        ("https://example.org/k", "aiohttp", "http"),
    ],
)
def test_missing_dependency_names_the_extra(monkeypatch, url, module, extra):
    """C-LOC-6: a missing provider package names the extra to install."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == module or name.startswith(module + "."):
            raise ImportError(f"No module named '{module}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RemoteStoreError) as exc:
        loc_mod.filesystem_for(StoreLocation.parse(url))
    assert exc.value.cause == "missing_dependency"
    assert f"ome-zarr-masker[{extra}]" in str(exc.value)


def test_core_import_pulls_in_no_provider_package():
    """Local users pay nothing for remote support (research R3).

    ``fsspec`` itself is not checked: zarr already imports it.
    """
    code = (
        "import sys, ome_zarr_masker.cli, ome_zarr_masker.api, ome_zarr_masker.io.location;"
        "bad=[m for m in ('s3fs','gcsfs','adlfs','aiohttp') if m in sys.modules];"
        "print(','.join(bad))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""


# -- provider filesystem options (research R4, T004) ------------------------------------------


class _Recorder:
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        type(self).calls.append(kwargs)


@pytest.fixture
def recorder():
    _Recorder.calls = []
    return _Recorder


def test_s3_options_anonymous_without_credentials(monkeypatch, recorder):
    import s3fs

    monkeypatch.setattr(s3fs, "S3FileSystem", recorder)
    monkeypatch.setattr(loc_mod, "_aws_credentials_available", lambda: False)
    loc_mod.filesystem_for(StoreLocation.parse("https://b.s3.us-west-2.amazonaws.com/k"))
    kw = recorder.calls[-1]
    assert kw["anon"] is True and kw["asynchronous"] is True
    assert kw["client_kwargs"] == {"region_name": "us-west-2"}


def test_s3_options_with_credentials(monkeypatch, recorder):
    import s3fs

    monkeypatch.setattr(s3fs, "S3FileSystem", recorder)
    monkeypatch.setattr(loc_mod, "_aws_credentials_available", lambda: True)
    loc_mod.filesystem_for(StoreLocation.parse("s3://b/k"))
    kw = recorder.calls[-1]
    assert "anon" not in kw and "client_kwargs" not in kw and kw["asynchronous"] is True


def test_gcs_options(monkeypatch, recorder):
    import gcsfs

    monkeypatch.setattr(gcsfs, "GCSFileSystem", recorder)
    loc_mod.filesystem_for(StoreLocation.parse("gs://b/k"))
    kw = recorder.calls[-1]
    assert kw["token"] is None and kw["asynchronous"] is True


def test_azure_options(monkeypatch, recorder):
    import adlfs

    monkeypatch.setattr(adlfs, "AzureBlobFileSystem", recorder)
    for var in loc_mod._AZURE_CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(loc_mod, "_azure_cli_logged_in", lambda: False)
    loc_mod.filesystem_for(StoreLocation.parse("https://acct.blob.core.windows.net/c/k"))
    kw = recorder.calls[-1]
    assert kw["account_name"] == "acct" and kw["asynchronous"] is True and kw["anon"] is True

    monkeypatch.setenv("AZURE_STORAGE_SAS_TOKEN", "sv=1&sig=x")
    loc_mod.filesystem_for(StoreLocation.parse("https://acct.blob.core.windows.net/c/k"))
    assert "anon" not in recorder.calls[-1]


def test_http_options(monkeypatch, recorder):
    from fsspec.implementations import http

    monkeypatch.setattr(http, "HTTPFileSystem", recorder)
    loc_mod.filesystem_for(StoreLocation.parse("https://example.org/k"))
    assert recorder.calls[-1]["asynchronous"] is True


def test_filesystem_override_hook(monkeypatch):
    sentinel = object()
    monkeypatch.setitem(loc_mod._FILESYSTEM_OVERRIDE, "s3", lambda location: sentinel)
    assert loc_mod.filesystem_for(StoreLocation.parse("s3://b/k")) is sentinel


# -- error mapping (research R6) -------------------------------------------------------------


class _StatusError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


@pytest.mark.parametrize(
    ("exc", "cause"),
    [
        (FileNotFoundError("nope"), "not_found"),
        (PermissionError("denied"), "forbidden"),
        (_StatusError(403), "forbidden"),
        (_StatusError(401), "forbidden"),
        (_StatusError(404), "not_found"),
        (TimeoutError("slow"), "network"),
        (ConnectionRefusedError("refused"), "network"),
        (OSError("reset"), "network"),
    ],
)
def test_error_mapping(exc, cause):
    loc = StoreLocation.parse("s3://b/k")
    mapped = loc_mod.map_remote_error(exc, loc)
    assert isinstance(mapped, RemoteStoreError)
    assert mapped.cause == cause
    assert mapped.location == "s3://b/k"
    assert "s3://b/k" in str(mapped)
    assert "\n" not in str(mapped)


def test_aiohttp_client_error_is_network():
    import aiohttp

    mapped = loc_mod.map_remote_error(aiohttp.ClientError("boom"), StoreLocation.parse("s3://b/k"))
    assert mapped is not None and mapped.cause == "network"


def test_wrapped_errors_are_found_through_the_chain():
    try:
        try:
            raise PermissionError("denied")
        except PermissionError as inner:
            raise RuntimeError("zarr failed") from inner
    except RuntimeError as outer:
        mapped = loc_mod.map_remote_error(outer, StoreLocation.parse("gs://b/k"))
    assert mapped is not None and mapped.cause == "forbidden"


def test_unrelated_errors_are_not_mapped():
    assert loc_mod.map_remote_error(ValueError("bad"), StoreLocation.parse("s3://b/k")) is None


def test_remote_errors_context_manager():
    loc = StoreLocation.parse("s3://b/k")
    with pytest.raises(RemoteStoreError) as exc, loc_mod.remote_errors(loc):
        raise FileNotFoundError("gone")
    assert exc.value.cause == "not_found"
    with pytest.raises(ValueError), loc_mod.remote_errors(loc):
        raise ValueError("passes through")
