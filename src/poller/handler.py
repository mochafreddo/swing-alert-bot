from __future__ import annotations

import os
from typing import Any, Dict, Optional

from common.telegram import TelegramClient, TelegramError
from state.models import State
from state.s3_store import S3StateStore


# Environment variable name for Telegram bot token
ENV_TELEGRAM_TOKEN = "SWING_TELEGRAM_TOKEN"


def _compute_next_offset(state: State) -> Optional[int]:
    """Return the offset to use for getUpdates based on stored state.

    Per Telegram docs: pass last_update_id + 1 to avoid receiving the last processed
    update again. If None, return None to start from earliest unconfirmed.
    """
    return state.last_update_id + 1 if state.last_update_id is not None else None


def _max_update_id(updates: list[dict]) -> Optional[int]:
    max_id: Optional[int] = None
    for upd in updates:
        try:
            uid = int(upd.get("update_id"))
        except Exception:
            continue
        max_id = uid if max_id is None else max(max_id, uid)
    return max_id


def run_once(*, allowed_updates: Optional[list[str]] = None, limit: int = 100, timeout: int = 0) -> Dict[str, Any]:
    """
    Poll Telegram getUpdates once, updating the stored last_update_id.

    - Loads encrypted state from S3 (env: SWING_STATE_BUCKET, SWING_STATE_KEY, SWING_FERNET_KEY).
    - Uses Telegram bot token from env SWING_TELEGRAM_TOKEN.
    - Calls getUpdates with offset = last_update_id + 1 (if available).
    - Writes back new last_update_id if new updates are received.

    Returns a summary dict: {"received": N, "new_last_update_id": int|None}.
    """
    token = os.environ.get(ENV_TELEGRAM_TOKEN)
    if not token:
        raise RuntimeError(f"Missing env: {ENV_TELEGRAM_TOKEN}")

    store = S3StateStore.from_env()
    state, etag = store.read()

    offset = _compute_next_offset(state)
    with TelegramClient(token) as tg:
        try:
            updates = tg.get_updates(offset=offset, limit=limit, timeout=timeout, allowed_updates=allowed_updates)
        except TelegramError as e:
            # Surface Telegram client errors as runtime failures for Lambda visibility
            raise RuntimeError(f"Telegram getUpdates failed: {e}") from e

    new_last = _max_update_id(updates)
    if new_last is not None and (state.last_update_id is None or new_last > state.last_update_id):
        state.last_update_id = new_last
        # Best-effort optimistic write if we have an etag; otherwise, simple put
        try:
            store.write(state, if_match=etag)
        except Exception:
            # Fallback without optimistic lock to avoid losing offset progression
            store.write(state)

    return {"received": len(updates), "new_last_update_id": state.last_update_id}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda entry point for scheduled Telegram command polling.

    Environment:
    - SWING_STATE_BUCKET, SWING_STATE_KEY, SWING_FERNET_KEY
    - SWING_TELEGRAM_TOKEN
    """
    # Default to only message updates for command handling
    allowed = ["message"]
    result = run_once(allowed_updates=allowed, limit=100, timeout=0)
    # Minimal log-friendly payload
    return {"ok": True, **result}
