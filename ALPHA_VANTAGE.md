# Alpha Vantage Client

Location: `src/common/alpha_vantage.py`

Features:

- Daily time series fetch (`adjusted` or not)
- Client-side rate limiting (sliding window, 5 req/min by default)
- Basic retry on transient errors (timeouts, 5xx, 429)
- Pydantic model (`Candle`) for parsed OHLCV rows

Usage:

```python
from common.alpha_vantage import AlphaVantageClient

API_KEY = "<your_av_key>"

with AlphaVantageClient(API_KEY) as av:
    candles = av.daily("AAPL", adjusted=True, outputsize="compact")
    # candles is a list[ C an dle ], newest first
    latest = candles[0]
    print(latest.ts, latest.close, latest.volume)
```

Notes:

- The client enforces 5 req/min locally via a sliding-window limiter. This helps
  avoid 429s, but still respect Alpha Vantage’s daily cap (500/day) in your calling code.
- Alpha Vantage’s free plan responses include `Note` when throttled; this client
  raises `AlphaVantageRateLimitError` on such payloads.
- For long runs with many symbols, consider sharding or upgrading your AV plan.
