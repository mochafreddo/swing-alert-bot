from __future__ import annotations

import importlib
import sys
import types

import pytest


# --- Optional stubs for boto3/botocore/cryptography (used only if missing) ---

def _install_optional_stubs():
    # Stub botocore.exceptions.ClientError if botocore isn't available
    if "botocore.exceptions" not in sys.modules:
        m_botocore = types.ModuleType("botocore")
        m_ex = types.ModuleType("botocore.exceptions")

        class ClientError(Exception):  # minimal shape used by code under test
            def __init__(self, response, operation_name):
                super().__init__(str(response))
                self.response = response
                self.operation_name = operation_name

        m_ex.ClientError = ClientError
        m_botocore.exceptions = m_ex
        sys.modules["botocore"] = m_botocore
        sys.modules["botocore.exceptions"] = m_ex

    # Stub boto3.client if boto3 isn't available
    if "boto3" not in sys.modules:
        m_boto3 = types.ModuleType("boto3")

        def client(*_args, **_kwargs):  # not used in tests (we inject s3)
            raise RuntimeError("boto3 client not available in test stub")

        m_boto3.client = client
        sys.modules["boto3"] = m_boto3

    # Stub cryptography.fernet.Fernet if cryptography isn't available
    if "cryptography.fernet" not in sys.modules:
        m_crypto = types.ModuleType("cryptography")
        m_fernet = types.ModuleType("cryptography.fernet")

        class InvalidToken(Exception):
            pass

        class Fernet:
            def __init__(self, key):
                self._key = key

            def encrypt(self, data: bytes) -> bytes:
                if not isinstance(data, (bytes, bytearray)):
                    raise TypeError("encrypt expects bytes")
                return b"enc:" + data

            def decrypt(self, token: bytes) -> bytes:
                if not isinstance(token, (bytes, bytearray)):
                    raise TypeError("decrypt expects bytes")
                if not token.startswith(b"enc:"):
                    raise InvalidToken("bad token")
                return token[4:]

        m_fernet.Fernet = Fernet
        m_fernet.InvalidToken = InvalidToken
        m_crypto.fernet = m_fernet
        sys.modules["cryptography"] = m_crypto
        sys.modules["cryptography.fernet"] = m_fernet


_install_optional_stubs()


# Import after stubs are in place
from state.models import State
from state.s3_store import S3StateStore


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3:
    def __init__(self) -> None:
        self._store = {}  # (bucket, key) -> {Body: bytes, ETag: str}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str):
        etag = f'"fake-{len(Body)}"'
        self._store[(Bucket, Key)] = {"Body": Body, "ETag": etag}
        return {"ETag": etag}

    def get_object(self, *, Bucket: str, Key: str):
        from botocore.exceptions import ClientError  # type: ignore

        item = self._store.get((Bucket, Key))
        if not item:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": _FakeBody(item["Body"]), "ETag": item["ETag"]}


def test_read_missing_returns_empty_state():
    s3 = _FakeS3()
    store = S3StateStore(s3=s3, bucket="b", key="k", fernet_key=b"f" * 32)

    state, etag = store.read()
    assert etag is None
    assert state.held == []
    assert state.alerts_sent == {}
    assert state.last_update_id is None


def test_write_and_read_roundtrip():
    s3 = _FakeS3()
    store = S3StateStore(s3=s3, bucket="b", key="k", fernet_key=b"f" * 32)

    src = State(held=["AAPL"], alerts_sent={"AAPL:2025-09-05:EMA_GC": True}, last_update_id=42)
    etag = store.write(src)
    assert etag.startswith('"fake-')

    dst, read_etag = store.read()
    assert read_etag == etag
    assert dst == src


def test_read_raises_value_error_on_bad_token():
    # Seed fake S3 with an invalid ciphertext (missing prefix expected by stub fernet)
    s3 = _FakeS3()
    s3.put_object(Bucket="b", Key="k", Body=b"garbage", ContentType="application/octet-stream")

    store = S3StateStore(s3=s3, bucket="b", key="k", fernet_key=b"f" * 32)
    with pytest.raises(ValueError):
        store.read()


def test_from_env_missing_vars_raises(monkeypatch):
    for name in ("SWING_STATE_BUCKET", "SWING_STATE_KEY", "SWING_FERNET_KEY"):
        monkeypatch.delenv(name, raising=False)

    # Re-import classmethod via importlib to avoid cached env in case of future changes
    mod = importlib.import_module("state.s3_store")
    with pytest.raises(RuntimeError):
        mod.S3StateStore.from_env()

