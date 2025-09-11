from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from common.alpha_vantage import AlphaVantageClient, Candle
from common.indicators import compute_indicators
from common.signals import gap_up_threshold, is_excessive_gap_up
from common.telegram import TelegramClient, TelegramError
from common.whitelist import parse_allowed_chat_ids, is_target_allowed
from state.models import State
from state.s3_store import S3StateStore


# Align env conventions with EOD runner for consistency
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


def _load_ssm_params(prefix: str, names: Iterable[str]) -> Dict[str, Optional[str]]:
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


# --- Open update formatting ---
@dataclass(frozen=True)
class OpenUpdate:
    symbol: str
    d_prev: date
    d_open: date
    prev_close: float
    open_price: float
    atr14_prev: Optional[float]
    threshold_level: float
    excessive: bool


def _fmt_money(v: float, *, currency: str = "$", decimals: int = 2) -> str:
    return f"{currency}{v:.{decimals}f}"


def format_open_update_msg(u: OpenUpdate) -> str:
    change_pct = (u.open_price - u.prev_close) / u.prev_close * 100.0 if u.prev_close else 0.0
    direction = "+" if change_pct >= 0 else ""
    header = f"🟢 [OPEN UPDATE] {u.symbol.upper()}"
    if u.excessive:
        status = (
            "Gap filter triggered: open is above threshold; hold base entry.\n"
            "Use intraday re-break or pullback per plan."
        )
    else:
        status = "Normal open: base entry allowed per plan."

    lines: list[str] = [
        header,
        status,
        "",
        "Open context:",
        f"- Prev close ({u.d_prev.isoformat()}): {_fmt_money(u.prev_close)}",
        f"- Today open ({u.d_open.isoformat()}): {_fmt_money(u.open_price)} ({direction}{change_pct:.1f}%)",
        f"- Threshold: {_fmt_money(u.threshold_level)} (min(3%, 1×ATR))",
    ]
    if u.atr14_prev is not None:
        lines.append(f"- ATR(14) (prev): {_fmt_money(u.atr14_prev)}")
    else:
        lines.append("- ATR(14): n/a")
    return "\n".join(lines)


# --- Core logic ---
def _parse_buy_candidate_keys(state: State) -> Dict[str, date]:
    """Return latest BUY_CANDIDATE date per symbol from state.alerts_sent.

    Keys follow the convention: "SYMBOL:YYYY-MM-DD:BUY_CANDIDATE".
    """
    latest: Dict[str, date] = {}
    for key in state.alerts_sent.keys():
        try:
            sym, d_str, code = key.split(":", 2)
        except Exception:
            continue
        if code != "BUY_CANDIDATE":
            continue
        try:
            year, month, day = (int(d_str[0:4]), int(d_str[5:7]), int(d_str[8:10]))
            d = date(year, month, day)
        except Exception:
            continue
        prev = latest.get(sym)
        latest[sym] = d if prev is None or d > prev else prev
    return latest


def _find_day_indices(candles_asc: List[Candle], target: date) -> Optional[Tuple[int, int]]:
    """Return (i_prev, i_open) where candles[i_prev].ts==target and candles[i_open] is the next day.

    Returns None if either day is not present (e.g., provider hasn't published today's candle yet).
    """
    idx_map = {c.ts: i for i, c in enumerate(candles_asc)}
    i_prev = idx_map.get(target)
    if i_prev is None:
        return None
    if i_prev + 1 >= len(candles_asc):
        return None
    return i_prev, i_prev + 1


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
            "allowed_chat_ids",  # optional whitelist
        ],
    )
    av_key = _require(params.get("alpha_vantage_api_key"), f"{prefix}alpha_vantage_api_key")
    tg_token = _require(params.get("telegram_bot_token"), f"{prefix}telegram_bot_token")
    tg_chat = _require(params.get("telegram_chat_id"), f"{prefix}telegram_chat_id")
    fernet_key = _require(params.get("fernet_key"), f"{prefix}fernet_key")

    # Parse whitelist and coerce chat id
    allowed_set = parse_allowed_chat_ids(params.get("allowed_chat_ids"))
    try:
        chat_id: int | str = int(tg_chat)
    except Exception:
        chat_id = tg_chat

    # If whitelist configured and target not allowed → no-op
    if allowed_set and not is_target_allowed(chat_id, allowed_set):
        return {"ok": True, "checked": 0, "updates": 0, "note": "telegram_chat_id not in allowed_chat_ids; skipped"}

    # Load state
    store = S3StateStore(bucket=bucket, key=key, fernet_key=fernet_key)
    state, etag = store.read()

    # Determine symbols that had BUY_CANDIDATE yesterday (latest per symbol)
    candidates_by_symbol = _parse_buy_candidate_keys(state)
    if not candidates_by_symbol:
        return {"ok": True, "checked": 0, "updates": 0, "note": "No prior buy candidates"}

    updates_sent = 0
    checked = 0

    with AlphaVantageClient(av_key) as av, TelegramClient(tg_token) as tg:
        
        for sym, d_prev in candidates_by_symbol.items():
            # Fetch daily series (descending newest-first), then make ascending
            try:
                daily_desc = av.daily(sym, adjusted=True, outputsize="compact")
            except Exception:
                continue
            if not daily_desc:
                continue
            candles_asc = list(reversed(daily_desc))

            idxs = _find_day_indices(candles_asc, d_prev)
            if idxs is None:
                # Either previous day missing or today not yet available
                continue
            i_prev, i_open = idxs
            prev_c = candles_asc[i_prev]
            open_c = candles_asc[i_open]

            # Compute indicators to obtain ATR(14) at previous day index
            try:
                series = compute_indicators(candles_asc)
                atr_prev = series.atr14[i_prev] if series.atr14 else None
            except Exception:
                atr_prev = None

            prev_close = float(prev_c.close)
            open_price = float(open_c.open)
            thr = gap_up_threshold(prev_close, atr_prev, pct=0.03, atr_mult=1.0)
            excessive = is_excessive_gap_up(prev_close, open_price, atr_prev, pct=0.03, atr_mult=1.0)

            # Dedup per open day
            dedup_key = f"{sym.upper()}:{open_c.ts.isoformat()}:OPEN_UPDATE"
            if state.alerts_sent.get(dedup_key):
                checked += 1
                continue

            msg = format_open_update_msg(
                OpenUpdate(
                    symbol=sym,
                    d_prev=prev_c.ts,
                    d_open=open_c.ts,
                    prev_close=prev_close,
                    open_price=open_price,
                    atr14_prev=float(atr_prev) if atr_prev is not None else None,
                    threshold_level=thr,
                    excessive=excessive,
                )
            )

            try:
                tg.send_message(chat_id=chat_id, text=msg)
            except TelegramError:
                # Do not mark dedup on send failure
                checked += 1
                continue

            state.alerts_sent[dedup_key] = True
            updates_sent += 1
            checked += 1

    # Persist state (best-effort optimistic write)
    try:
        store.write(state, if_match=etag)
    except Exception:
        store.write(state)

    return {"ok": True, "checked": checked, "updates": updates_sent}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    return run_once()
