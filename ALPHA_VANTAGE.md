# Alpha Vantage Client

Location: `src/common/alpha_vantage.py`

Features:

- Daily time series fetch (`adjusted` or not)
- Client-side rate limiting (sliding window, 5 req/min by default)
- Basic retry on transient errors (timeouts, 5xx, 429)
- Pydantic model (`Candle`) for parsed OHLCV rows
- Optional freshness cache to skip unchanged data (`daily_if_changed`)

Usage:

```python
from common.alpha_vantage import AlphaVantageClient

API_KEY = "<your_av_key>"

with AlphaVantageClient(API_KEY) as av:
    candles = av.daily("AAPL", adjusted=True, outputsize="compact")
    # candles is a list[ C an dle ], newest first
    latest = candles[0]
    print(latest.ts, latest.close, latest.volume)
    
    # Or: only process when there's new data since the last run
    maybe = av.daily_if_changed("AAPL", adjusted=True, outputsize="compact")
    if maybe is None:
        print("No change since last run; skipping heavy work")
    else:
        print(f"Changed. Newest date: {maybe[0].ts}")
```

Notes:

- The client enforces 5 req/min locally via a sliding-window limiter. This helps
  avoid 429s, but still respect Alpha Vantage’s daily cap (500/day) in your calling code.
- Alpha Vantage’s free plan responses include `Note` when throttled; this client
  raises `AlphaVantageRateLimitError` on such payloads.
- For long runs with many symbols, consider sharding or upgrading your AV plan.

Caching:

- The client provides `daily_if_changed(...)` which uses a small JSON cache to remember
  the newest candle date per symbol. It returns `None` when the provider's newest date
  matches the last run, helping you skip redundant processing.
- The cache file defaults to `.cache/av_daily_meta.json`. Set `SWING_CACHE_DIR` to change
  the directory (the file name stays `av_daily_meta.json`).
- Cache entry schema: `{ "{SYMBOL}:{adj|raw}": { "last_refreshed": "YYYY-MM-DD", "last_checked_at": "YYYY-MM-DDTHH:MM:SS+00:00" } }`.
  Timestamps are timezone-aware ISO 8601 with explicit `+00:00` offset (UTC).
