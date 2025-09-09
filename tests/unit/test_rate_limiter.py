from __future__ import annotations

import threading

import pytest

from common.rate_limiter import SlidingWindowRateLimiter, RateLimitError


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:  # acts like time.monotonic
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_non_blocking_exceeds_limit():
    clock = FakeClock()
    rl = SlidingWindowRateLimiter(max_calls=2, per_seconds=60.0, clock=clock)

    rl.acquire(blocking=True)
    rl.acquire(blocking=True)
    with pytest.raises(RateLimitError):
        rl.acquire(blocking=False)

    clock.advance(60.0)
    rl.acquire(blocking=False)  # now allowed


def test_blocking_allows_after_window_expires():
    clock = FakeClock()
    rl = SlidingWindowRateLimiter(max_calls=1, per_seconds=10.0, clock=clock)

    rl.acquire(blocking=True)

    # Simulate waiting via advancing the clock and acquiring from another thread.
    # Since acquire sleeps based on real time, we won't actually wait; instead,
    # we verify internal logic by advancing clock before second acquire.
    clock.advance(10.0)
    rl.acquire(blocking=True)  # should succeed immediately after window

