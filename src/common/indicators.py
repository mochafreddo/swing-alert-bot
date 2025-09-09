from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

from .alpha_vantage import Candle


@dataclass
class IndicatorSeries:
    """
    Computed indicator series aligned to dates in ascending order (oldest -> newest).

    Fields contain `None` for positions where insufficient history exists for the period.
    """

    dates: List[date]
    closes: List[float]
    ema20: List[Optional[float]]
    ema50: List[Optional[float]]
    rsi14: List[Optional[float]]
    atr14: List[Optional[float]]
    sma200: List[Optional[float]]


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be positive")


def sma(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Simple moving average.

    Returns a list aligned to `values` with `None` until enough data is available.
    """
    _validate_period(period)
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    window_sum = sum(values[0:period])
    out[period - 1] = window_sum / period
    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        out[i] = window_sum / period
    return out


def ema(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Exponential moving average using standard smoothing (alpha = 2/(N+1)).

    Seeded with the SMA of the first `period` values.
    Returns a list aligned to `values` with `None` until the seed index.
    """
    _validate_period(period)
    n = len(values)
    out: List[Optional[float]] = [None] * n
    if n == 0:
        return out
    if n < period:
        return out
    # Seed with SMA
    seed = sum(values[:period]) / period
    k = 2.0 / (period + 1.0)
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def rsi(closes: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index (Wilder's smoothing).

    - Computes close-to-close deltas.
    - Initial average gain/loss computed over the first `period` deltas.
    - Then uses Wilder's smoothing: avg = (prev_avg*(period-1) + current)/period.
    - Returns `None` until the first RSI point (index `period`).
    """
    _validate_period(period)
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out

    gains: List[float] = [0.0] * n
    losses: List[float] = [0.0] * n
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains[i] = delta
            losses[i] = 0.0
        else:
            gains[i] = 0.0
            losses[i] = -delta

    # Seed averages using the first `period` deltas (indices 1..period)
    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period

    def _compute_rsi(avg_g: float, avg_l: float) -> float:
        if avg_l == 0.0:
            return 100.0 if avg_g > 0.0 else 0.0
        rs = avg_g / avg_l
        return 100.0 - (100.0 / (1.0 + rs))

    out[period] = _compute_rsi(avg_gain, avg_loss)

    # Wilder smoothing for subsequent points
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i] = _compute_rsi(avg_gain, avg_loss)

    return out


def atr(candles: Sequence[Candle], period: int = 14) -> List[Optional[float]]:
    """Average True Range (Wilder's) from a sequence of `Candle`s.

    The input order is respected. ATR uses TR defined as:
      TR = max( high - low, abs(high - prev_close), abs(low - prev_close) ).
    The first TR uses `high - low` (no previous close).
    Returns `None` until the first ATR point (index `period - 1`).
    """
    _validate_period(period)
    n = len(candles)
    out: List[Optional[float]] = [None] * n
    if n == 0:
        return out

    # Compute TR series
    tr: List[float] = [0.0] * n
    prev_close: Optional[float] = None
    for i, c in enumerate(candles):
        if prev_close is None:
            tr[i] = c.high - c.low
        else:
            tr1 = c.high - c.low
            tr2 = abs(c.high - prev_close)
            tr3 = abs(c.low - prev_close)
            tr[i] = max(tr1, tr2, tr3)
        prev_close = c.close

    if n < period:
        return out

    # Seed ATR as the simple average of first `period` TR values
    seed = sum(tr[:period]) / period
    out[period - 1] = seed

    atr_prev = seed
    for i in range(period, n):
        atr_prev = (atr_prev * (period - 1) + tr[i]) / period
        out[i] = atr_prev
    return out


def compute_indicators(candles: Sequence[Candle]) -> IndicatorSeries:
    """
    Compute EMA(20/50), RSI(14), ATR(14), SMA(200) over the provided candles.

    - Sorts by date ascending to apply smoothing correctly.
    - Returns an `IndicatorSeries` with lists aligned to the sorted order.
    """
    if not candles:
        return IndicatorSeries([], [], [], [], [], [], [])

    # Sort oldest -> newest for stable smoothing
    ordered = sorted(candles, key=lambda c: c.ts)
    closes = [c.close for c in ordered]

    ema20_series = ema(closes, 20)
    ema50_series = ema(closes, 50)
    rsi14_series = rsi(closes, 14)
    atr14_series = atr(ordered, 14)
    sma200_series = sma(closes, 200)

    return IndicatorSeries(
        dates=[c.ts for c in ordered],
        closes=closes,
        ema20=ema20_series,
        ema50=ema50_series,
        rsi14=rsi14_series,
        atr14=atr14_series,
        sma200=sma200_series,
    )


def latest_values(series: IndicatorSeries) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Return the latest (newest) values for EMA20, EMA50, RSI14, ATR14.

    SMA200 can be obtained from `series.sma200[-1]` if needed. This helper keeps
    parity with the task focus (EMA/RSI/ATR + SMA).
    """
    if not series.dates:
        return None, None, None, None
    return series.ema20[-1], series.ema50[-1], series.rsi14[-1], series.atr14[-1]


__all__ = [
    "IndicatorSeries",
    "sma",
    "ema",
    "rsi",
    "atr",
    "compute_indicators",
    "latest_values",
]

