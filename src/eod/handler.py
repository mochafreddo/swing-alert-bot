from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from common.alpha_vantage import AlphaVantageClient, Candle
from common.cache import SymbolUpdateCache
from common.indicators import compute_indicators
from common.signals import evaluate_long_candidate
from common.alerts import BuyCandidateContext, format_buy_candidate_alert
from common.telegram import TelegramClient, TelegramError
from common.whitelist import parse_allowed_chat_ids, is_target_allowed
from state.s3_store import S3StateStore
from state.models import State


# Environment variable names expected (aligned with Terraform README example)
ENV_STATE_BUCKET = "STATE_BUCKET"
ENV_STATE_KEY = "STATE_KEY"  # optional; defaults to "state.json"
ENV_PARAM_PREFIX = "PARAM_PREFIX"

# Backward-compatible fallbacks (if using earlier env naming)
FALLBACK_ENV_STATE_BUCKET = "SWING_STATE_BUCKET"
FALLBACK_ENV_STATE_KEY = "SWING_STATE_KEY"
FALLBACK_ENV_PARAM_PREFIX = "SWING_PARAM_PREFIX"


def _getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _require(v: Optional[str], what: str) -> str:
    if not v:
        raise RuntimeError(f"Missing required configuration: {what}")
    return v


def _load_ssm_params(prefix: str, names: Iterable[str]) -> Dict[str, Optional[str]]:
    ssm = boto3.client("ssm")
    out: Dict[str, Optional[str]] = {k: None for k in names}
    for name in names:
        full = f"{prefix}{name}"
        try:
            resp = ssm.get_parameter(Name=full, WithDecryption=True)
        except ClientError as e:
            # Leave as None if parameter missing or access denied
            code = e.response.get("Error", {}).get("Code")
            if code in ("ParameterNotFound", "AccessDeniedException"):
                out[name] = None
                continue
            raise
        val = resp.get("Parameter", {}).get("Value")
        out[name] = val if isinstance(val, str) and val != "" else None
    return out


def _parse_watchlist(s: Optional[str]) -> List[str]:
    if not s:
        return []
    raw = s.replace("\n", ",").replace(" ", ",")
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
    # Dedup while preserving order
    seen: set[str] = set()
    out: List[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _dedup_key(symbol: str, d: date, code: str) -> str:
    return f"{symbol.upper()}:{d.isoformat()}:{code}"


def run_once() -> Dict[str, Any]:
    # Resolve env configuration
    bucket = _getenv(ENV_STATE_BUCKET) or _getenv(FALLBACK_ENV_STATE_BUCKET)
    key = _getenv(ENV_STATE_KEY, "state.json") or _getenv(FALLBACK_ENV_STATE_KEY, "state.json")
    prefix = _getenv(ENV_PARAM_PREFIX) or _getenv(FALLBACK_ENV_PARAM_PREFIX)

    bucket = _require(bucket, ENV_STATE_BUCKET)
    prefix = _require(prefix, ENV_PARAM_PREFIX)

    # Load required secrets from SSM
    params = _load_ssm_params(
        prefix,
        [
            "alpha_vantage_api_key",
            "telegram_bot_token",
            "telegram_chat_id",
            "fernet_key",
            "watchlist",  # optional
            "allowed_chat_ids",  # optional whitelist
        ],
    )
    av_key = _require(params.get("alpha_vantage_api_key"), f"{prefix}alpha_vantage_api_key")
    tg_token = _require(params.get("telegram_bot_token"), f"{prefix}telegram_bot_token")
    tg_chat = _require(params.get("telegram_chat_id"), f"{prefix}telegram_chat_id")
    fernet_key = _require(params.get("fernet_key"), f"{prefix}fernet_key")

    # Parse whitelist and coerce chat id
    allowed_set = parse_allowed_chat_ids(params.get("allowed_chat_ids"))
    # Chat id can be int or str
    try:
        chat_id: int | str = int(tg_chat)
    except Exception:
        chat_id = tg_chat

    # If whitelist configured and target not allowed → no-op
    if allowed_set and not is_target_allowed(chat_id, allowed_set):
        return {
            "ok": True,
            "scanned": 0,
            "changed": 0,
            "candidates": 0,
            "alerts": 0,
            "note": "telegram_chat_id not in allowed_chat_ids; skipped",
        }

    # Load state
    store = S3StateStore(bucket=bucket, key=key, fernet_key=fernet_key)
    state, etag = store.read()

    # Compose universe: optional watchlist + always include held
    watchlist = _parse_watchlist(params.get("watchlist"))
    universe: List[str] = list(watchlist)
    for t in state.held:
        tt = t.strip().upper()
        if tt and tt not in universe:
            universe.append(tt)

    # No symbols to process → return early
    if not universe:
        return {
            "ok": True,
            "scanned": 0,
            "changed": 0,
            "candidates": 0,
            "alerts": 0,
            "note": "Empty universe (no watchlist or held)",
        }

    cache = SymbolUpdateCache()
    alerts_sent = 0
    candidates_found = 0
    changed_symbols = 0

    # Prepare clients
    with AlphaVantageClient(av_key) as av, TelegramClient(tg_token) as tg:
        for sym in universe:
            try:
                candles = av.daily_if_changed(sym, adjusted=True, outputsize="compact", cache=cache)
            except Exception:
                continue

            if candles is None:
                continue
            changed_symbols += 1

            try:
                series = compute_indicators(list(reversed(candles)))  # ensure oldest->newest before sort
                cand = evaluate_long_candidate(sym, series)
            except Exception:
                continue

            if cand is None or not cand.ok():
                continue

            candidates_found += 1

            # Dedup by date + code
            key_code = _dedup_key(sym, cand.date, "BUY_CANDIDATE")
            if state.alerts_sent.get(key_code):
                continue

            # Build alert message
            latest_close = series.closes[-1] if series.closes else None
            latest_atr = series.atr14[-1] if series.atr14 else None
            if latest_close is None:
                continue

            ctx = BuyCandidateContext(
                symbol=sym,
                close_price=float(latest_close),
                atr14=(float(latest_atr) if latest_atr is not None else None),
                above_sma200=cand.above_sma200,
                ema20_cross_above_ema50=cand.golden_cross_20_50,
                rsi14_recross_above_30=cand.rsi_recross_above_30,
            )
            msg = format_buy_candidate_alert(ctx)

            try:
                tg.send_message(chat_id=chat_id, text=msg)
            except TelegramError:
                continue

            state.alerts_sent[key_code] = True
            alerts_sent += 1

    # Persist updated state
    try:
        store.write(state, if_match=etag)
    except Exception:
        store.write(state)

    return {
        "ok": True,
        "scanned": len(universe),
        "changed": changed_symbols,
        "candidates": candidates_found,
        "alerts": alerts_sent,
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    return run_once()
