from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from common.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageRateLimitError,
    AlphaVantageApiError,
)
from common.cache import SymbolUpdateCache


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


def _payload_with_meta(last_refreshed: str) -> Dict[str, Any]:
    """Adjusted-style payload including Meta Data["3. Last Refreshed"]."""
    return {
        "Meta Data": {
            "1. Information": "Daily Time Series with Splits and Dividend Events",
            "2. Symbol": "AAPL",
            "3. Last Refreshed": last_refreshed,
        },
        "Time Series (Daily)": {
            last_refreshed.split(" ")[0]: {
                "1. open": "110.0",
                "2. high": "115.0",
                "3. low": "109.0",
                "4. close": "114.0",
                "5. adjusted close": "113.8",
                "6. volume": "1200000",
                "7. dividend amount": "0.00",
                "8. split coefficient": "1.0",
            },
            "2024-09-02": {
                "1. open": "105.0",
                "2. high": "111.0",
                "3. low": "100.0",
                "4. close": "110.0",
                "5. adjusted close": "109.6",
                "6. volume": "1400000",
                "7. dividend amount": "0.00",
                "8. split coefficient": "1.0",
            },
        },
    }


def _payload_plain_with_series_only(newest_date: str) -> Dict[str, Any]:
    return {
        # Intentionally omit Meta Data to exercise series-key fallback
        "Time Series (Daily)": {
            newest_date: {
                "1. open": "10.0",
                "2. high": "11.0",
                "3. low": "9.5",
                "4. close": "10.5",
                "5. volume": "1000",
            },
            "2024-09-01": {
                "1. open": "9.0",
                "2. high": "10.0",
                "3. low": "8.5",
                "4. close": "9.8",
                "5. volume": "1100",
            },
        },
    }


def test_daily_if_changed_caches_and_skips_when_unchanged(tmp_path):
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        # Same newest date both times
        return httpx.Response(200, json=_payload_with_meta("2024-09-03 16:00:00"))

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10.0)
    cache = SymbolUpdateCache(path=tmp_path / "cache.json")
    with AlphaVantageClient("DUMMY", client=client) as av:
        first = av.daily_if_changed("AAPL", adjusted=True, outputsize="compact", cache=cache)
        second = av.daily_if_changed("AAPL", adjusted=True, outputsize="compact", cache=cache)

    # Two network calls (freshness check each time)
    assert calls["n"] == 2
    # First call returns candles, second returns None
    assert first is not None
    assert second is None
    # Cache stores newest date
    assert cache.get_last_refreshed("AAPL", adjusted=True) == "2024-09-03"


def test_daily_if_changed_detects_new_date_and_updates_cache(tmp_path):
    state = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(200, json=_payload_with_meta("2024-09-03 16:00:00"))
        return httpx.Response(200, json=_payload_with_meta("2024-09-04 16:00:00"))

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10.0)
    cache = SymbolUpdateCache(path=tmp_path / "cache.json")
    with AlphaVantageClient("DUMMY", client=client) as av:
        first = av.daily_if_changed("AAPL", adjusted=True, outputsize="compact", cache=cache)
        second = av.daily_if_changed("AAPL", adjusted=True, outputsize="compact", cache=cache)

    assert state["n"] == 2
    assert first is not None
    assert second is not None  # changed
    assert second[0].ts.isoformat() == "2024-09-04"
    assert cache.get_last_refreshed("AAPL", adjusted=True) == "2024-09-04"


def test_daily_if_changed_series_key_fallback(tmp_path):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload_plain_with_series_only("2024-09-02"))

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10.0)
    cache = SymbolUpdateCache(path=tmp_path / "cache.json")
    with AlphaVantageClient("DUMMY", client=client) as av:
        out = av.daily_if_changed("MSFT", adjusted=False, outputsize="compact", cache=cache)

    assert out is not None
    assert out[0].ts.isoformat() == "2024-09-02"
    # Cache should use series max key (no Meta Data available)
    assert cache.get_last_refreshed("MSFT", adjusted=False) == "2024-09-02"


def test_daily_if_changed_raises_on_empty_series():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Meta Data": {}, "Time Series (Daily)": {}})

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10.0)
    with AlphaVantageClient("DUMMY", client=client) as av:
        with pytest.raises(AlphaVantageApiError):
            av.daily_if_changed("AAPL")


def test_daily_if_changed_separate_cache_keys_for_adjusted_flag(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        fn = req.url.params.get("function")
        if fn == "TIME_SERIES_DAILY_ADJUSTED":
            return httpx.Response(200, json=_payload_with_meta("2024-09-03 16:00:00"))
        # Non-adjusted payload shape
        return httpx.Response(200, json={
            "Meta Data": {
                "1. Information": "Daily Prices (open, high, low, close) and Volumes",
                "2. Symbol": "AAPL",
                "3. Last Refreshed": "2024-09-03 16:00:00",
            },
            "Time Series (Daily)": {
                "2024-09-03": {
                    "1. open": "108.0",
                    "2. high": "112.0",
                    "3. low": "105.0",
                    "4. close": "111.0",
                    "5. volume": "900000",
                },
                "2024-09-02": {
                    "1. open": "100.0",
                    "2. high": "110.0",
                    "3. low": "95.0",
                    "4. close": "108.0",
                    "5. volume": "1000000",
                },
            },
        })

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=10.0)
    cache = SymbolUpdateCache(path=tmp_path / "cache.json")
    with AlphaVantageClient("DUMMY", client=client) as av:
        out_adj = av.daily_if_changed("AAPL", adjusted=True, outputsize="compact", cache=cache)
        out_raw = av.daily_if_changed("AAPL", adjusted=False, outputsize="compact", cache=cache)

    assert out_adj is not None and out_raw is not None
    # Separate keys maintained
    assert cache.get_last_refreshed("AAPL", adjusted=True) == "2024-09-03"
    assert cache.get_last_refreshed("AAPL", adjusted=False) == "2024-09-03"
