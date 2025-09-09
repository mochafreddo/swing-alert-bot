from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Literal, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

from .rate_limiter import SlidingWindowRateLimiter, RateLimitError
from .cache import SymbolUpdateCache


DEFAULT_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageError(RuntimeError):
    """Base error for Alpha Vantage client."""


class AlphaVantageApiError(AlphaVantageError):
    """API returned an error payload or unexpected structure."""


class AlphaVantageRateLimitError(AlphaVantageError):
    """Local or remote rate limiting prevented the request."""


class Candle(BaseModel):
    ts: date = Field(..., description="Trading day")
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjusted_close: Optional[float] = None
    dividend_amount: Optional[float] = None
    split_coefficient: Optional[float] = None


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


class AlphaVantageClient:
    """
    Minimal Alpha Vantage client with client-side throttling.

    Notes
    - Free plan: 5 req/min, 500 req/day. This client enforces a local 5 RPM
      sliding-window limit by default to reduce 429s. It does not enforce the
      daily quota.
    - Network errors and 5xx are retried with exponential backoff.
    - Provides helpers for Daily (adjusted/non-adjusted) time series.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        max_per_minute: int = 5,
        timeout: float = 15.0,
        client: Optional[httpx.Client] = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("?")
        self._timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=self._timeout)
        self._limiter = SlidingWindowRateLimiter(max_calls=max_per_minute, per_seconds=60.0)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "AlphaVantageClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --------------- Public API ---------------
    def daily(
        self,
        symbol: str,
        *,
        adjusted: bool = True,
        outputsize: Literal["compact", "full"] = "full",
    ) -> List[Candle]:
        """
        Fetch daily time series for `symbol`.

        - `adjusted=True` uses `TIME_SERIES_DAILY_ADJUSTED` (incl. splits/dividends).
        - `outputsize`: "compact" (last 100) or "full" (full history).

        Returns newest-first candles (descending by date).
        """
        fn = "TIME_SERIES_DAILY_ADJUSTED" if adjusted else "TIME_SERIES_DAILY"
        params = {
            "function": fn,
            "symbol": symbol,
            "outputsize": outputsize,
            "datatype": "json",
        }
        data = self._request(params)
        try:
            return self._parse_daily_payload(data, adjusted=adjusted)
        except ValidationError as ve:  # from pydantic model validation
            raise AlphaVantageApiError(f"Failed to parse daily payload: {ve}") from ve

    def daily_if_changed(
        self,
        symbol: str,
        *,
        adjusted: bool = True,
        outputsize: Literal["compact", "full"] = "full",
        cache: Optional[SymbolUpdateCache] = None,
    ) -> Optional[List[Candle]]:
        """
        Fetch daily series only if the provider's newest date differs from last run.

        - Uses a simple persistent cache to remember the newest candle date per symbol.
        - Returns a list of candles when changed; returns None when unchanged.

        Notes
        - This still performs a single API call to validate freshness. It avoids
          downstream processing if data is unchanged. To fully avoid network calls
          on repeated same-day runs, a higher-level scheduler policy is preferred.
        """
        fn = "TIME_SERIES_DAILY_ADJUSTED" if adjusted else "TIME_SERIES_DAILY"
        params = {
            "function": fn,
            "symbol": symbol,
            "outputsize": outputsize,
            "datatype": "json",
        }
        data = self._request(params)
        newest_date_iso = self._extract_newest_date_iso(data)

        c = cache or SymbolUpdateCache()
        prev = c.get_last_refreshed(symbol, adjusted=adjusted)
        if prev is not None and prev == newest_date_iso:
            # Update last-checked timestamp for observability, keep same date
            c.set_last_refreshed(symbol, adjusted=adjusted, last_refreshed=prev)
            return None

        # Parse and persist the new newest date
        try:
            candles = self._parse_daily_payload(data, adjusted=adjusted)
        except ValidationError as ve:
            raise AlphaVantageApiError(f"Failed to parse daily payload: {ve}") from ve
        c.set_last_refreshed(symbol, adjusted=adjusted, last_refreshed=newest_date_iso)
        return candles

    # --------------- Internal ---------------
    def _request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # Merge the apikey
        query = {**params, "apikey": self._api_key}

        # Throttle locally using sliding window
        try:
            self._limiter.acquire(blocking=True)
        except RateLimitError as rl:
            raise AlphaVantageRateLimitError("Local rate limiter prevented request") from rl

        # Basic retry with exponential backoff on transient errors
        attempt = 0
        backoff = 1.0
        last_exc: Optional[Exception] = None
        while attempt < 4:
            try:
                resp = self._client.get(self._base_url, params=query)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
            else:
                if resp.status_code == 200:
                    payload = resp.json()
                    self._raise_on_api_error(payload)
                    return payload  # type: ignore[return-value]
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_exc = AlphaVantageApiError(
                        f"HTTP {resp.status_code} from Alpha Vantage"
                    )
                else:
                    raise AlphaVantageApiError(
                        f"HTTP {resp.status_code} from Alpha Vantage: {resp.text[:200]}"
                    )

            # Retry path
            attempt += 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

        # Exhausted retries
        if last_exc is not None:
            raise AlphaVantageError("Failed request after retries") from last_exc
        raise AlphaVantageError("Failed request after retries (unknown error)")

    @staticmethod
    def _raise_on_api_error(payload: Dict[str, Any]) -> None:
        # API returns one of these keys for problems
        if "Error Message" in payload:
            raise AlphaVantageApiError(payload.get("Error Message", "API error"))
        if "Note" in payload:
            # Usually rate limiting note
            raise AlphaVantageRateLimitError(payload.get("Note", "Rate limit exceeded"))
        if "Information" in payload:
            raise AlphaVantageApiError(payload.get("Information", "API info message"))

    @staticmethod
    def _parse_daily_payload(payload: Dict[str, Any], *, adjusted: bool) -> List[Candle]:
        # Locate series key; both adjusted and non-adjusted use "Time Series (Daily)"
        series_key = None
        for k in payload.keys():
            if k.startswith("Time Series (Daily)"):
                series_key = k
                break
        if not series_key:
            raise AlphaVantageApiError("Daily series missing in payload")

        series: Dict[str, Dict[str, str]] = payload[series_key]
        items: List[Candle] = []
        for ts_str, fields in series.items():
            ts = _parse_date(ts_str)
            if adjusted:
                # Adjusted daily has 8 fields
                item = Candle(
                    ts=ts,
                    open=float(fields["1. open"]),
                    high=float(fields["2. high"]),
                    low=float(fields["3. low"]),
                    close=float(fields["4. close"]),
                    adjusted_close=float(fields.get("5. adjusted close", fields["4. close"])),
                    volume=int(float(fields["6. volume"])),
                    dividend_amount=float(fields.get("7. dividend amount", 0.0)),
                    split_coefficient=float(fields.get("8. split coefficient", 1.0)),
                )
            else:
                item = Candle(
                    ts=ts,
                    open=float(fields["1. open"]),
                    high=float(fields["2. high"]),
                    low=float(fields["3. low"]),
                    close=float(fields["4. close"]),
                    volume=int(float(fields["5. volume"])),
                )
            items.append(item)

        # API returns newest first already; ensure descending by date
        items.sort(key=lambda c: c.ts, reverse=True)
        return items

    @staticmethod
    def _extract_newest_date_iso(payload: Dict[str, Any]) -> str:
        """
        Determine the newest candle date as YYYY-MM-DD.

        Prefers Meta Data["3. Last Refreshed"] when available; otherwise falls back
        to max(Time Series (Daily).keys()). Handles timestamps by truncating to date.
        """
        # Try Meta Data first
        meta = payload.get("Meta Data")
        if isinstance(meta, dict):
            last = meta.get("3. Last Refreshed") or meta.get("3. Last Refreshed ")
            if isinstance(last, str) and last:
                # Could be "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
                return last.split(" ")[0]

        # Fallback: inspect series keys
        series_key = None
        for k in payload.keys():
            if k.startswith("Time Series (Daily)"):
                series_key = k
                break
        if not series_key:
            raise AlphaVantageApiError("Daily series missing in payload")
        series: Dict[str, Dict[str, str]] = payload[series_key]
        if not series:
            raise AlphaVantageApiError("Daily series is empty")
        # Keys are YYYY-MM-DD
        newest = max(series.keys())
        return newest


__all__ = [
    "AlphaVantageClient",
    "AlphaVantageError",
    "AlphaVantageApiError",
    "AlphaVantageRateLimitError",
    "Candle",
]
