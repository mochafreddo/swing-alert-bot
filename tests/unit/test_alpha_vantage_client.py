from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from common.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageRateLimitError,
)


def _daily_adjusted_payload() -> Dict[str, Any]:
    # Two days, intentionally added in ascending order to test client sorting
    return {
        "Meta Data": {
            "1. Information": "Daily Time Series with Splits and Dividend Events",
            "2. Symbol": "AAPL",
        },
        "Time Series (Daily)": {
            "2024-09-01": {
                "1. open": "100.0",
                "2. high": "110.0",
                "3. low": "95.0",
                "4. close": "108.0",
                "5. adjusted close": "107.5",
                "6. volume": "1000000",
                "7. dividend amount": "0.00",
                "8. split coefficient": "1.0",
            },
            "2024-09-03": {
                "1. open": "108.0",
                "2. high": "112.0",
                "3. low": "105.0",
                "4. close": "111.0",
                "5. adjusted close": "110.7",
                "6. volume": "900000",
                "7. dividend amount": "0.00",
                "8. split coefficient": "1.0",
            },
        },
    }


def _daily_plain_payload() -> Dict[str, Any]:
    return {
        "Meta Data": {
            "1. Information": "Daily Prices (open, high, low, close) and Volumes",
            "2. Symbol": "AAPL",
        },
        "Time Series (Daily)": {
            "2024-09-03": {
                "1. open": "108.0",
                "2. high": "112.0",
                "3. low": "105.0",
                "4. close": "111.0",
                "5. volume": "900000",
            },
            "2024-09-01": {
                "1. open": "100.0",
                "2. high": "110.0",
                "3. low": "95.0",
                "4. close": "108.0",
                "5. volume": "1000000",
            },
        },
    }


def test_daily_adjusted_parsing_and_sorting():
    calls = {"count": 0, "last_request": None}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        calls["last_request"] = request
        return httpx.Response(200, json=_daily_adjusted_payload())

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10.0)
    with AlphaVantageClient("DUMMY", client=client) as av:
        candles = av.daily("AAPL", adjusted=True, outputsize="compact")

    assert calls["count"] == 1
    req = calls["last_request"]
    assert req is not None
    # Ensure correct function parameter used
    assert req.url.params.get("function") == "TIME_SERIES_DAILY_ADJUSTED"
    assert req.url.params.get("symbol") == "AAPL"

    # Check sorting: newest first
    assert candles[0].ts.isoformat() == "2024-09-03"
    assert candles[1].ts.isoformat() == "2024-09-01"

    # Check field mapping for adjusted series
    latest = candles[0]
    assert latest.open == 108.0
    assert latest.high == 112.0
    assert latest.low == 105.0
    assert latest.close == 111.0
    assert latest.adjusted_close == 110.7
    assert latest.volume == 900000
    assert latest.dividend_amount == 0.0
    assert latest.split_coefficient == 1.0


def test_daily_plain_parsing():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_daily_plain_payload())

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10.0)
    with AlphaVantageClient("DUMMY", client=client) as av:
        candles = av.daily("AAPL", adjusted=False, outputsize="compact")

    assert candles[0].ts.isoformat() == "2024-09-03"
    assert candles[0].adjusted_close is None  # not present in non-adjusted series
    assert candles[0].volume == 900000


def test_api_throttle_note_raises():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute and 500 calls per day."})

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10.0)
    with AlphaVantageClient("DUMMY", client=client) as av:
        with pytest.raises(AlphaVantageRateLimitError):
            av.daily("AAPL")


def test_retry_on_500_then_success():
    state = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(500, text="server error")
        return httpx.Response(200, json=_daily_adjusted_payload())

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10.0)
    with AlphaVantageClient("DUMMY", client=client) as av:
        candles = av.daily("AAPL")

    assert state["n"] == 2
    assert len(candles) == 2

