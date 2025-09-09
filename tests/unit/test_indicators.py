from __future__ import annotations

from common.alpha_vantage import Candle
from common.indicators import sma, ema, rsi, atr, compute_indicators


def _mk(
    ymd: str,
    o: float,
    h: float,
    l: float,
    c: float,
    v: int = 0,
) -> Candle:
    from datetime import datetime

    return Candle(
        ts=datetime.strptime(ymd, "%Y-%m-%d").date(),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def test_sma_ema_basic():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    s = sma(closes, 3)
    e = ema(closes, 3)
    assert s == [None, None, 2.0, 3.0, 4.0]
    assert e == [None, None, 2.0, 3.0, 4.0]


def test_rsi_wilder_uptrend_all_gains():
    # Monotonic up: RSI should be 100 once available
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    out = rsi(closes, 3)
    assert out[:3] == [None, None, None]
    assert out[3] == 100.0
    assert out[4] == 100.0


def test_atr_wilder_simple():
    # Construct a simple set where TR is easy to compute
    candles = [
        _mk("2024-01-01", 10, 12, 9, 11),
        _mk("2024-01-02", 11, 13, 10, 12),
        _mk("2024-01-03", 12, 14, 11, 13),
        _mk("2024-01-04", 13, 15, 12, 14),
        _mk("2024-01-05", 14, 17, 13, 16),
    ]
    # ATR(3): seed = (3 + 3 + 3)/3 = 3.0, then stays 3.0, then (3*2+4)/3 = 10/3
    out = atr(candles, 3)
    assert out[0] is None and out[1] is None
    assert out[2] == 3.0
    assert out[3] == 3.0
    assert abs(out[4] - (10.0 / 3.0)) < 1e-9


def test_compute_indicators_sorts_and_aligns():
    # Provide out-of-order candles and ensure ascending alignment and lengths
    candles = [
        _mk("2024-01-03", 12, 14, 11, 13),
        _mk("2024-01-01", 10, 12, 9, 11),
        _mk("2024-01-02", 11, 13, 10, 12),
    ]
    series = compute_indicators(candles)
    # Ascending order by date
    assert [d.isoformat() for d in series.dates] == [
        "2024-01-01",
        "2024-01-02",
        "2024-01-03",
    ]
    assert len(series.closes) == 3
    assert len(series.ema20) == 3
    assert len(series.ema50) == 3
    assert len(series.rsi14) == 3
    assert len(series.atr14) == 3
    assert len(series.sma200) == 3

