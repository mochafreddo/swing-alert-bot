from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from cryptography.fernet import Fernet, InvalidToken

from .models import State


# Environment variable names for convenience configuration
ENV_BUCKET = "SWING_STATE_BUCKET"
ENV_KEY = "SWING_STATE_KEY"
ENV_FERNET_KEY = "SWING_FERNET_KEY"


def _to_fernet(key: str | bytes) -> Fernet:
    """Construct a Fernet instance from a user-provided key.

    The key must be a URL-safe base64-encoded 32-byte key (str or bytes),
    as returned by `cryptography.fernet.Fernet.generate_key()`.
    """
    if isinstance(key, str):
        key_bytes = key.encode("utf-8")
    else:
        key_bytes = key
    return Fernet(key_bytes)


def _dump_state_json(state: State) -> bytes:
    # Deterministic JSON: stable key order, no extra whitespace
    payload = json.dumps(
        state.model_dump(), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return payload


def _load_state_json(data: bytes) -> State:
    raw = json.loads(data.decode("utf-8"))
    return State.model_validate(raw)


@dataclass
class S3ObjectRef:
    bucket: str
    key: str


class S3StateStore:
    """
    S3-backed persistence for `State`, encrypted at rest using Fernet.

    Usage
    - Provide S3 bucket/key and a Fernet key (from env or injected).
    - `read()` returns a `(state, etag)` pair. If the object does not exist,
      it returns `(State.empty(), None)`.
    - `write(state, if_match=None)` writes the encrypted bytes and returns the new ETag.
      The `if_match` argument is reserved for a future optimistic-locking enhancement;
      it is currently ignored by S3 PutObject and will be wired up in a later task.

    Environment variables (optional)
    - `SWING_STATE_BUCKET`: S3 bucket for the state object
    - `SWING_STATE_KEY`:    S3 key (path) for the state object
    - `SWING_FERNET_KEY`:   urlsafe base64-encoded key for Fernet
    """

    def __init__(
        self,
        *,
        s3: Optional[object] = None,
        bucket: str,
        key: str,
        fernet_key: str | bytes,
        region_name: Optional[str] = None,
    ) -> None:
        self._s3 = s3 or boto3.client("s3", region_name=region_name)
        self._obj = S3ObjectRef(bucket=bucket, key=key)
        self._fernet = _to_fernet(fernet_key)

    # -------- Construction helpers --------
    @classmethod
    def from_env(cls) -> "S3StateStore":
        bucket = os.environ.get(ENV_BUCKET)
        key = os.environ.get(ENV_KEY)
        fkey = os.environ.get(ENV_FERNET_KEY)
        if not bucket or not key or not fkey:
            missing = [
                name for name, val in [(ENV_BUCKET, bucket), (ENV_KEY, key), (ENV_FERNET_KEY, fkey)] if not val
            ]
            raise RuntimeError(
                f"Missing required environment variables for S3 state store: {', '.join(missing)}"
            )
        return cls(bucket=bucket, key=key, fernet_key=fkey)

    # -------- Core operations --------
    def read(self) -> Tuple[State, Optional[str]]:
        """Read and decrypt State from S3.

        Returns: (state, etag)
        - If object not found, returns (State.empty(), None).
        Raises:
        - ValueError if decryption fails or content is invalid JSON.
        - botocore.exceptions.ClientError for other S3 issues.
        """
        try:
            resp = self._s3.get_object(Bucket=self._obj.bucket, Key=self._obj.key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                return (State.empty(), None)
            raise

        body = resp["Body"].read()
        etag = resp.get("ETag")  # usually quoted string
        try:
            decrypted = self._fernet.decrypt(body)
        except InvalidToken as ex:
            raise ValueError("Failed to decrypt state: invalid Fernet token") from ex

        try:
            state = _load_state_json(decrypted)
        except Exception as ex:
            raise ValueError("Failed to parse decrypted state JSON") from ex

        return (state, etag)

    def write(self, state: State, *, if_match: Optional[str] = None) -> str:
        """Encrypt and write State to S3; returns the new ETag.

        Args:
        - state: the State to persist.
        - if_match: reserved for future optimistic-locking. Currently not enforced
          for PutObject; will be integrated via a copy-based conditional update in
          a subsequent task.
        """
        plaintext = _dump_state_json(state)
        ciphertext = self._fernet.encrypt(plaintext)

        # Note: S3 PutObject does not honor If-Match; we ignore `if_match` for now.
        resp = self._s3.put_object(
            Bucket=self._obj.bucket,
            Key=self._obj.key,
            Body=ciphertext,
            ContentType="application/octet-stream",
        )
        return str(resp.get("ETag"))


# -------- Convenience top-level helpers --------
def load_state_from_s3(*, bucket: str, key: str, fernet_key: str | bytes, region_name: Optional[str] = None) -> Tuple[State, Optional[str]]:
    store = S3StateStore(bucket=bucket, key=key, fernet_key=fernet_key, region_name=region_name)
    return store.read()


def save_state_to_s3(
    state: State,
    *,
    bucket: str,
    key: str,
    fernet_key: str | bytes,
    region_name: Optional[str] = None,
    if_match: Optional[str] = None,
) -> str:
    store = S3StateStore(bucket=bucket, key=key, fernet_key=fernet_key, region_name=region_name)
    return store.write(state, if_match=if_match)

