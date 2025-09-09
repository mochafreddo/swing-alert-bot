"""
Common utilities for swing-alert-bot.

Modules:
- alpha_vantage: Alpha Vantage API client with rate limiting
- indicators: Pure-Python TA indicators (EMA, RSI, ATR, SMA)
- signals: Signal detection (crossovers, RSI re-cross, gap filter)
"""

__all__ = [
    "alpha_vantage",
    "indicators",
    "signals",
]
