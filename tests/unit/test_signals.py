from __future__ import annotations

from datetime import date

from common.indicators import IndicatorSeries
from common.signals import (
    is_golden_cross_today,
    is_death_cross_today,
    rsi_recross_above_today,
    rsi_recross_below_today,
    gap_up_threshold,
    is_excessive_gap_up,
    evaluate_long_candidate,
)


def test_golden_cross_today_basic():
    # prev: fast <= slow, curr: fast > slow
    ema_fast = [None, 10.0, 10.0, 11.0]
    ema_slow = [None, 10.0, 10.5, 10.7]
    assert is_golden_cross_today(ema_fast, ema_slow) is True


def test_golden_cross_today_false_when_no_cross():
    # Always above (no cross today)
    ema_fast = [None, 10.0, 10.6, 10.7]
    ema_slow = [None, 10.0, 10.5, 10.6]
    assert is_golden_cross_today(ema_fast, ema_slow) is False


def test_death_cross_today_basic():
    # prev: fast >= slow, curr: fast < slow
    ema_fast = [None, 10.0, 10.6, 10.4]
    ema_slow = [None, 10.0, 10.5, 10.5]
    assert is_death_cross_today(ema_fast, ema_slow) is True


def test_rsi_recross_above_below():
    rsi_series = [None, 28.0, 31.0]
    assert rsi_recross_above_today(rsi_series, 30.0) is True

    rsi_series2 = [None, 72.0, 69.0]
    assert rsi_recross_below_today(rsi_series2, 70.0) is True


def test_gap_up_threshold_and_detection():
    prev_close = 100.0
    atr = 2.0
    level = gap_up_threshold(prev_close, atr, pct=0.03, atr_mult=1.0)
    # min(3%, 1*ATR) => min(3.0, 2.0) = 2.0 -> level = 102.0
    assert abs(level - 102.0) < 1e-9
    assert is_excessive_gap_up(prev_close, 104.0, atr) is True
    assert is_excessive_gap_up(prev_close, 101.0, atr) is False


def test_evaluate_long_candidate_ok():
    # Construct a minimal synthetic IndicatorSeries where all conditions hold
    dates = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    closes = [100.0, 102.0, 105.0]
    ema20 = [None, 100.0, 101.0]
    ema50 = [None, 100.5, 100.8]
    rsi14 = [None, 28.0, 31.0]
    atr14 = [None, None, 2.5]
    sma200 = [None, None, 99.0]
    series = IndicatorSeries(
        dates=dates,
        closes=closes,
        ema20=ema20,
        ema50=ema50,
        rsi14=rsi14,
        atr14=atr14,
        sma200=sma200,
    )

    cand = evaluate_long_candidate("TEST", series)
    assert cand is not None
    assert cand.ok() is True


def test_evaluate_long_candidate_insufficient_history_returns_none():
    # Missing latest EMA/SMA/RSI values
    dates = [date(2024, 1, 1), date(2024, 1, 2)]
    series = IndicatorSeries(
        dates=dates,
        closes=[100.0, 101.0],
        ema20=[None, None],
        ema50=[None, None],
        rsi14=[None, None],
        atr14=[None, None],
        sma200=[None, None],
    )
    assert evaluate_long_candidate("TEST", series) is None

