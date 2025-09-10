from common.alerts import BuyCandidateContext, format_buy_candidate_alert


def test_format_buy_candidate_with_atr():
    ctx = BuyCandidateContext(
        symbol="AAPL",
        close_price=151.0,
        atr14=3.1,
        above_sma200=True,
        ema20_cross_above_ema50=True,
        rsi14_recross_above_30=True,
    )
    msg = format_buy_candidate_alert(ctx)

    # Header and action
    assert msg.startswith("🟢 [BUY CANDIDATE] AAPL\nAction today:")

    # Reasons should include all three
    assert "- EMA20 crossed above EMA50" in msg
    assert "- Price above 200SMA" in msg
    assert "- RSI(14) bounced above 30" in msg

    # Risk guide includes ATR, stop, target and ratio
    assert "Risk guide:" in msg
    assert "- ATR(14): $3.10" in msg
    assert "- Stop:" in msg and "Target:" in msg
    assert "R:R" in msg


def test_format_buy_candidate_without_atr():
    ctx = BuyCandidateContext(
        symbol="MSFT",
        close_price=420.0,
        atr14=None,
        above_sma200=False,
        ema20_cross_above_ema50=False,
        rsi14_recross_above_30=False,
    )
    msg = format_buy_candidate_alert(ctx)

    # Header
    assert msg.startswith("🟢 [BUY CANDIDATE] MSFT\nAction today:")

    # Should fall back to generic reason line if none of the specific reasons apply
    assert "Meets strategy conditions" in msg

    # Risk guide should show ATR n/a if missing
    assert "- ATR(14): n/a" in msg

