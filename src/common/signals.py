from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

from .indicators import IndicatorSeries


# -------------------- Low-level helpers --------------------

def _last_two(values: Sequence[Optional[float]]) -> Optional[Tuple[float, float]]:
    """Return (prev, curr) when the last two entries are non-None.

    Returns None if the sequence has fewer than 2 items or if either of the
    last two values is None.
    """
    if len(values) < 2:
        return None
    prev = values[-2]
    curr = values[-1]
    if prev is None or curr is None:
        return None
    return float(prev), float(curr)


def crossed_above(prev_a: float, prev_b: float, curr_a: float, curr_b: float) -> bool:
    """Return True if `a` crossed above `b` on the latest bar.

    Uses inclusive previous comparison (prev_a <= prev_b and curr_a > curr_b)
    to treat an equality on the previous bar as a valid cross when it resolves
    upward on the current bar.
    """
    return prev_a <= prev_b and curr_a > curr_b


def crossed_below(prev_a: float, prev_b: float, curr_a: float, curr_b: float) -> bool:
    """Return True if `a` crossed below `b` on the latest bar.

    Uses inclusive previous comparison (prev_a >= prev_b and curr_a < curr_b).
    """
    return prev_a >= prev_b and curr_a < curr_b


def recrossed_above(prev_value: float, curr_value: float, threshold: float) -> bool:
    """Return True if value crossed back above `threshold` on latest bar.

    prev_value <= threshold and curr_value > threshold.
    """
    return prev_value <= threshold and curr_value > threshold


def recrossed_below(prev_value: float, curr_value: float, threshold: float) -> bool:
    """Return True if value crossed back below `threshold` on latest bar.

    prev_value >= threshold and curr_value < threshold.
    """
    return prev_value >= threshold and curr_value < threshold


# -------------------- Public crossover / recross checks --------------------

def is_golden_cross_today(ema_fast: Sequence[Optional[float]], ema_slow: Sequence[Optional[float]]) -> bool:
    """EMA fast crossed above EMA slow on the most recent bar.

    Typically used for EMA20 vs EMA50 (bullish).
    """
    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return False
    pair_fast = _last_two(ema_fast)
    pair_slow = _last_two(ema_slow)
    if pair_fast is None or pair_slow is None:
        return False
    (pf, cf) = pair_fast
    (ps, cs) = pair_slow
    return crossed_above(pf, ps, cf, cs)


def is_death_cross_today(ema_fast: Sequence[Optional[float]], ema_slow: Sequence[Optional[float]]) -> bool:
    """EMA fast crossed below EMA slow on the most recent bar (bearish)."""
    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return False
    pair_fast = _last_two(ema_fast)
    pair_slow = _last_two(ema_slow)
    if pair_fast is None or pair_slow is None:
        return False
    (pf, cf) = pair_fast
    (ps, cs) = pair_slow
    return crossed_below(pf, ps, cf, cs)


def rsi_recross_above_today(rsi_series: Sequence[Optional[float]], threshold: float = 30.0) -> bool:
    """RSI crossed back above `threshold` (default 30) on the most recent bar."""
    pair = _last_two(rsi_series)
    if pair is None:
        return False
    prev, curr = pair
    return recrossed_above(prev, curr, threshold)


def rsi_recross_below_today(rsi_series: Sequence[Optional[float]], threshold: float = 70.0) -> bool:
    """RSI crossed back below `threshold` (default 70) on the most recent bar."""
    pair = _last_two(rsi_series)
    if pair is None:
        return False
    prev, curr = pair
    return recrossed_below(prev, curr, threshold)


# -------------------- Gap filter --------------------

def gap_up_threshold(prev_close: float, atr_value: Optional[float], *, pct: float = 0.03, atr_mult: float = 1.0) -> float:
    """Compute the absolute price threshold for an excessive gap-up.

    Threshold amount added to prev_close is min(prev_close*pct, atr_mult*atr_value) when
    ATR is available; otherwise falls back to percent-only.
    Returns the price level (prev_close + threshold_amount).
    """
    pct_amt = prev_close * pct
    if atr_value is None:
        thr_amt = pct_amt
    else:
        thr_amt = min(pct_amt, atr_mult * float(atr_value))
    return prev_close + thr_amt


def is_excessive_gap_up(prev_close: float, today_open: float, atr_value: Optional[float], *, pct: float = 0.03, atr_mult: float = 1.0) -> bool:
    """Return True if open >= prev_close + min(prev_close*pct, atr_mult*ATR).

    Mirrors the design doc's gap filter to hold base entry at the open.
    """
    level = gap_up_threshold(prev_close, atr_value, pct=pct, atr_mult=atr_mult)
    return today_open >= level


# -------------------- Composite candidate checks --------------------

@dataclass
class LongCandidate:
    date: date
    symbol: str
    above_sma200: bool
    golden_cross_20_50: bool
    rsi_recross_above_30: bool

    def ok(self) -> bool:
        return self.above_sma200 and self.golden_cross_20_50 and self.rsi_recross_above_30


def evaluate_long_candidate(symbol: str, series: IndicatorSeries) -> Optional[LongCandidate]:
    """Evaluate long candidate per design doc on the latest bar.

    Conditions (buy candidate):
    - Close > SMA200
    - EMA20 crosses above EMA50 (today)
    - RSI crosses back above 30 (today)

    Returns LongCandidate if evaluable (i.e., indicators available). Returns None
    if there isn't enough history to compute the required indicators.
    """
    if not series.dates:
        return None

    # Availability checks for required latest indicators
    latest_close = series.closes[-1] if series.closes else None
    latest_sma200 = series.sma200[-1] if series.sma200 else None
    latest_rsi = series.rsi14[-1] if series.rsi14 else None
    latest_ema20 = series.ema20[-1] if series.ema20 else None
    latest_ema50 = series.ema50[-1] if series.ema50 else None

    # Require latest indicators to be present (not None) and at least 2 points for crossover checks
    if (
        latest_close is None
        or latest_sma200 is None
        or latest_rsi is None
        or latest_ema20 is None
        or latest_ema50 is None
        or len(series.ema20) < 2
        or len(series.ema50) < 2
        or len(series.rsi14) < 2
    ):
        return None

    above_sma200 = latest_close > float(latest_sma200)
    golden_cross = is_golden_cross_today(series.ema20, series.ema50)
    rsi_recross = rsi_recross_above_today(series.rsi14, 30.0)

    return LongCandidate(
        date=series.dates[-1],
        symbol=symbol,
        above_sma200=above_sma200,
        golden_cross_20_50=golden_cross,
        rsi_recross_above_30=rsi_recross,
    )


__all__ = [
    "is_golden_cross_today",
    "is_death_cross_today",
    "rsi_recross_above_today",
    "rsi_recross_below_today",
    "gap_up_threshold",
    "is_excessive_gap_up",
    "LongCandidate",
    "evaluate_long_candidate",
]

