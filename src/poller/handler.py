from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, Tuple

from common.telegram import TelegramClient, TelegramError
from state.models import State
from state.s3_store import S3StateStore


# Environment variable name for Telegram bot token
ENV_TELEGRAM_TOKEN = "SWING_TELEGRAM_TOKEN"
_BUY_RE = re.compile(r"^\s*/buy\s+([A-Za-z0-9.\-]{1,15})\s*$", re.IGNORECASE)
_SELL_RE = re.compile(r"^\s*/sell\s+([A-Za-z0-9.\-]{1,15})\s*$", re.IGNORECASE)
_LIST_RE = re.compile(r"^\s*/list\s*$", re.IGNORECASE)


def _normalize_ticker(t: str) -> str:
    return t.strip().upper()


def _parse_buy(text: str) -> Optional[str]:
    m = _BUY_RE.match(text or "")
    if not m:
        return None
    return _normalize_ticker(m.group(1))


def _apply_buy(state: State, ticker: str) -> Tuple[bool, str]:
    """Apply a /buy command to State. Returns (changed, message)."""
    if ticker in state.held:
        return (False, f"Already marked as held: {ticker}")
    state.held.append(ticker)
    # keep a stable canonical order for ergonomics
    try:
        state.held.sort()
    except Exception:
        pass
    return (True, f"✅ Marked as held: {ticker}")


def _parse_sell(text: str) -> Optional[str]:
    m = _SELL_RE.match(text or "")
    if not m:
        return None
    return _normalize_ticker(m.group(1))


def _apply_sell(state: State, ticker: str) -> Tuple[bool, str]:
    """Apply a /sell command to State. Returns (changed, message)."""
    if ticker not in state.held:
        return (False, f"Not currently held: {ticker}")
    try:
        state.held = [t for t in state.held if t != ticker]
    except Exception:
        # Fallback to in-place remove if list comprehension fails for any reason
        try:
            state.held.remove(ticker)
        except Exception:
            pass
    return (True, f"✅ Unmarked: {ticker}")


def _parse_list(text: str) -> bool:
    return _LIST_RE.match(text or "") is not None


def _format_list_response(state: State) -> str:
    if not state.held:
        return "Held list is empty."
    # Ensure stable order for display
    try:
        tickers = sorted(state.held)
    except Exception:
        tickers = list(state.held)
    return f"Held tickers ({len(tickers)}): " + ", ".join(tickers)


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

        # Process commands: /buy TICKER, /sell TICKER, /list
        acks: list[tuple[int | str, str]] = []
        for upd in updates:
            msg = upd.get("message") if isinstance(upd, dict) else None
            if not isinstance(msg, dict):
                continue
            text = msg.get("text")
            if not isinstance(text, str):
                continue
            chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else None
            chat_id = chat.get("id") if isinstance(chat, dict) else None
            if chat_id is None:
                continue

            # Try /buy
            ticker = _parse_buy(text)
            if ticker is not None:
                changed, ack = _apply_buy(state, ticker)
                acks.append((chat_id, ack))
                continue

            # Try /sell
            ticker = _parse_sell(text)
            if ticker is not None:
                changed, ack = _apply_sell(state, ticker)
                acks.append((chat_id, ack))
                continue

            # Try /list
            if _parse_list(text):
                acks.append((chat_id, _format_list_response(state)))
                continue

        # Send acknowledgements back to the originating chats
        for chat_id, ack in acks:
            try:
                tg.send_message(chat_id=chat_id, text=ack)
            except TelegramError:
                # Ignore send errors for acks to avoid failing the whole poll cycle
                pass

    new_last = _max_update_id(updates)
    if new_last is not None and (state.last_update_id is None or new_last > state.last_update_id):
        state.last_update_id = new_last
        # Best-effort optimistic write if we have an etag; otherwise, simple put
        try:
            store.write(state, if_match=etag)
        except Exception:
            # Fallback without optimistic lock to avoid losing offset progression or /buy updates
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
