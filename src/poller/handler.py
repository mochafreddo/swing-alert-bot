from __future__ import annotations

import os
import re
import json
from typing import Any, Dict, Optional, Tuple, Union, List, Set

from common.telegram import TelegramClient, TelegramError
from state.models import State
from state.s3_store import S3StateStore


# Environment configuration (aligned with EOD/Open runners)
ENV_STATE_BUCKET = "STATE_BUCKET"
ENV_STATE_KEY = "STATE_KEY"  # optional; defaults to "state.json"
ENV_PARAM_PREFIX = "PARAM_PREFIX"

# Backward-compatible fallbacks
FALLBACK_ENV_STATE_BUCKET = "SWING_STATE_BUCKET"
FALLBACK_ENV_STATE_KEY = "SWING_STATE_KEY"
FALLBACK_ENV_PARAM_PREFIX = "SWING_PARAM_PREFIX"


def _getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _require(v: Optional[str], what: str) -> str:
    if not v:
        raise RuntimeError(f"Missing required configuration: {what}")
    return v


def _load_ssm_params(prefix: str, names: list[str]) -> Dict[str, Optional[str]]:
    import boto3
    from botocore.exceptions import ClientError

    ssm = boto3.client("ssm")
    out: Dict[str, Optional[str]] = {k: None for k in names}
    for name in names:
        full = f"{prefix}{name}"
        try:
            resp = ssm.get_parameter(Name=full, WithDecryption=True)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("ParameterNotFound", "AccessDeniedException"):
                out[name] = None
                continue
            raise
        val = resp.get("Parameter", {}).get("Value")
        out[name] = val if isinstance(val, str) and val != "" else None
    return out


def _parse_allowed_chat_ids(raw: Optional[str]) -> Set[Union[int, str]]:
    """Parse allowed chat ids from CSV or JSON array.

    Accepts either:
    - JSON array: e.g., "[12345, -67890, \"@mychannel\"]"
    - CSV (commas/newlines/spaces treated as separators): "12345, -67890, @mychannel"

    Returns a set of chat identifiers (ints for numeric ids, str otherwise).
    Empty or invalid input yields an empty set.
    """
    if not raw or not isinstance(raw, str):
        return set()

    # Try JSON first
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            out: Set[Union[int, str]] = set()
            for item in data:
                # Convert numbers to int, strings kept as-is
                if isinstance(item, bool):
                    # Avoid True/False being treated as 1/0
                    continue
                if isinstance(item, (int,)):
                    out.add(int(item))
                elif isinstance(item, (float,)):
                    # Only accept float that is integral
                    if float(item).is_integer():
                        out.add(int(item))
                elif isinstance(item, str):
                    s = item.strip()
                    if s:
                        # Try to coerce numeric strings (including negatives)
                        try:
                            out.add(int(s))
                        except Exception:
                            out.add(s)
            return out
    except Exception:
        pass

    # Fallback to CSV parsing; split on commas/newlines/spaces
    # Normalize separators to commas, then split
    norm = raw.replace("\n", ",").replace(" ", ",")
    items: List[str] = [tok.strip() for tok in norm.split(",") if tok.strip()]
    out2: Set[Union[int, str]] = set()
    for tok in items:
        # Trim surrounding quotes
        if (tok.startswith("\"") and tok.endswith("\"")) or (tok.startswith("'") and tok.endswith("'")):
            tok = tok[1:-1]
        try:
            out2.add(int(tok))
        except Exception:
            out2.add(tok)
    return out2


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
    Poll Telegram getUpdates once, processing basic commands and updating state.

    - Resolves state bucket/key and SSM prefix from env, with fallbacks.
    - Loads Telegram bot token and Fernet key from SSM via prefix.
    - Reads encrypted state from S3.
    - Calls getUpdates with offset = last_update_id + 1 (if available).
    - Applies /buy, /sell, /list and sends acknowledgements.
    - Writes back new last_update_id (and any held changes).

    Returns: {"ok": True, "received": N, "new_last_update_id": int|None}.
    """
    # Resolve env configuration
    bucket = _getenv(ENV_STATE_BUCKET) or _getenv(FALLBACK_ENV_STATE_BUCKET)
    key = _getenv(ENV_STATE_KEY, "state.json") or _getenv(FALLBACK_ENV_STATE_KEY, "state.json")
    prefix = _getenv(ENV_PARAM_PREFIX) or _getenv(FALLBACK_ENV_PARAM_PREFIX)

    bucket = _require(bucket, ENV_STATE_BUCKET)
    prefix = _require(prefix, ENV_PARAM_PREFIX)

    # Load secrets from SSM
    params = _load_ssm_params(prefix, ["telegram_bot_token", "fernet_key", "allowed_chat_ids"])
    token = _require(params.get("telegram_bot_token"), f"{prefix}telegram_bot_token")
    fernet_key = _require(params.get("fernet_key"), f"{prefix}fernet_key")
    # Parse whitelist (no-op in this step; enforcement handled separately)
    _ = _parse_allowed_chat_ids(params.get("allowed_chat_ids"))

    # State store
    store = S3StateStore(bucket=bucket, key=key, fernet_key=fernet_key)
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

    return {"ok": True, "received": len(updates), "new_last_update_id": state.last_update_id}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda entry for scheduled Telegram command polling.

    Environment:
    - STATE_BUCKET, STATE_KEY (default: state.json), PARAM_PREFIX
    - Fallbacks: SWING_STATE_BUCKET, SWING_STATE_KEY, SWING_PARAM_PREFIX
    - SSM under PARAM_PREFIX must provide: telegram_bot_token, fernet_key
    """
    # Only message updates are needed for command handling
    allowed = ["message"]
    return run_once(allowed_updates=allowed, limit=100, timeout=0)
