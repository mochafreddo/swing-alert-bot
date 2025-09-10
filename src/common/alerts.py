from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .signals import long_stop_target


@dataclass(frozen=True)
class BuyCandidateContext:
    """Context for formatting a buy-candidate alert.

    Attributes
    - symbol: Ticker symbol
    - close_price: Latest close price (assumed entry reference)
    - atr14: Latest ATR(14) value if available
    - above_sma200: Price above SMA200 on latest close
    - ema20_cross_above_ema50: EMA20 crossed above EMA50 on the latest bar
    - rsi14_recross_above_30: RSI(14) recrossed above 30 on the latest bar
    """

    symbol: str
    close_price: float
    atr14: Optional[float]
    above_sma200: bool
    ema20_cross_above_ema50: bool
    rsi14_recross_above_30: bool


def _fmt_money(value: float, *, currency: str = "$", decimals: int = 2) -> str:
    return f"{currency}{value:.{decimals}f}"


def _fmt_ratio(entry: float, stop: float, target: float) -> str:
    # Avoid division by zero; if invalid, omit ratio
    risk = max(entry - stop, 0.0)
    reward = max(target - entry, 0.0)
    if risk <= 0.0 or reward <= 0.0:
        return ""
    rr = reward / risk
    # Round to nearest 0.1 for readability
    rr_disp = round(rr, 1)
    return f"(≈1:{rr_disp:g} R:R)"


def format_buy_candidate_alert(ctx: BuyCandidateContext, *, currency: str = "$") -> str:
    """Return a beginner-friendly, action-oriented buy-candidate alert message.

    The layout follows the PRD/TECHNICAL_DESIGN examples. Gracefully degrades
    when ATR is unavailable.
    """
    header = f"🟢 [BUY CANDIDATE] {ctx.symbol.upper()}"
    action = (
        "Action today: Decide if you will enter at the next U.S. market open"
    )

    reasons: list[str] = []
    if ctx.ema20_cross_above_ema50:
        reasons.append("- EMA20 crossed above EMA50 (uptrend)")
    if ctx.above_sma200:
        reasons.append("- Price above 200SMA")
    if ctx.rsi14_recross_above_30:
        reasons.append("- RSI(14) bounced above 30")
    # Ensure we always show something under 'Why:'
    if not reasons:
        reasons.append("- Meets strategy conditions on the latest bar")

    plan = (
        "- Base: enter at next open\n"
        "- Exception: if open gap > 3% or >1×ATR → wait for intraday re-break or pullback"
    )

    risk_lines: list[str] = []
    if ctx.atr14 is not None and ctx.atr14 > 0.0:
        risk_lines.append(f"- ATR(14): {_fmt_money(ctx.atr14, currency=currency)}")
        st = long_stop_target(ctx.close_price, ctx.atr14)
        if st is not None:
            stop, target = st
            ratio = _fmt_ratio(ctx.close_price, stop, target)
            risk_lines.append(
                f"- Stop: {_fmt_money(stop, currency=currency)} / Target: {_fmt_money(target, currency=currency)} {ratio}".rstrip()
            )
    else:
        risk_lines.append("- ATR(14): n/a")

    # Assemble message
    parts = [
        header,
        action,
        "",
        "Why:",
        *reasons,
        "",
        "Plan:",
        plan,
        "",
        "Risk guide:",
        *risk_lines,
        "Validity: 3 trading days",
    ]
    return "\n".join(parts)


__all__ = [
    "BuyCandidateContext",
    "format_buy_candidate_alert",
]

