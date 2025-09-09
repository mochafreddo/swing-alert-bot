from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


class RateLimitError(RuntimeError):
    """Raised when a non-blocking acquire would exceed the rate limit."""


@dataclass
class _WindowConfig:
    max_calls: int
    per_seconds: float


class SlidingWindowRateLimiter:
    """
    A simple thread-safe sliding-window rate limiter.

    - Ensures at most `max_calls` happen within any `per_seconds` window.
    - If `blocking=True`, waits until a slot is available.
    - If `blocking=False`, raises `RateLimitError` when a slot isn't available.

    Designed for single-process Lambda execution where calls are made from
    one or more threads. Not a distributed limiter.
    """

    def __init__(self, max_calls: int, per_seconds: float, *, clock=time.monotonic):
        if max_calls <= 0:
            raise ValueError("max_calls must be > 0")
        if per_seconds <= 0:
            raise ValueError("per_seconds must be > 0")
        self._cfg = _WindowConfig(max_calls=max_calls, per_seconds=per_seconds)
        self._events: Deque[float] = deque()
        self._lock = threading.Lock()
        self._clock = clock

    def _prune(self, now: float) -> None:
        """Drop timestamps that are outside the current window."""
        window_start = now - self._cfg.per_seconds
        while self._events and self._events[0] <= window_start:
            self._events.popleft()

    def _next_available_delay(self, now: float) -> float:
        """Return seconds to wait until the next slot is available (>= 0)."""
        if len(self._events) < self._cfg.max_calls:
            return 0.0
        # Oldest event determines when a new slot opens
        oldest = self._events[0]
        return max(0.0, (oldest + self._cfg.per_seconds) - now)

    def acquire(self, *, blocking: bool = True) -> None:
        """
        Acquire a permit to proceed.

        - If `blocking`, sleeps until allowed.
        - If not, raises RateLimitError if a slot is not immediately available.
        """
        while True:
            with self._lock:
                now = self._clock()
                self._prune(now)
                delay = self._next_available_delay(now)
                if delay == 0.0:
                    self._events.append(now)
                    return
            if not blocking:
                raise RateLimitError("rate limit exceeded; no slot available")
            time.sleep(min(delay, 1.0))  # sleep in small chunks for responsiveness

