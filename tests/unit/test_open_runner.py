from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest


def _patch_params(monkeypatch: pytest.MonkeyPatch) -> None:
    # Replace SSM loader with a static dict to avoid boto3
    from open import handler as openmod

    def fake_load_ssm_params(prefix: str, names: list[str]) -> Dict[str, Optional[str]]:  # noqa: ARG001
        return {
            "alpha_vantage_api_key": "DUMMY-AV",
            "telegram_bot_token": "DUMMY-TG",
            "telegram_chat_id": "123456",
            "fernet_key": "A" * 43,
        }

    monkeypatch.setenv("STATE_BUCKET", "test-bucket")
    monkeypatch.setenv("STATE_KEY", "state.json")
    monkeypatch.setenv("PARAM_PREFIX", "/swing/dev/")
    monkeypatch.setattr(openmod, "_load_ssm_params", fake_load_ssm_params)


def _patch_params_with_whitelist(monkeypatch: pytest.MonkeyPatch, allowed_value: str) -> None:
    # Replace SSM loader with a static dict including a whitelist
    from open import handler as openmod

    def fake_load_ssm_params(prefix: str, names: list[str]) -> Dict[str, Optional[str]]:  # noqa: ARG001
        return {
            "alpha_vantage_api_key": "DUMMY-AV",
            "telegram_bot_token": "DUMMY-TG",
            "telegram_chat_id": "123456",
            "fernet_key": "A" * 43,
            "allowed_chat_ids": allowed_value,
        }

    monkeypatch.setenv("STATE_BUCKET", "test-bucket")
    monkeypatch.setenv("STATE_KEY", "state.json")
    monkeypatch.setenv("PARAM_PREFIX", "/swing/dev/")
    monkeypatch.setattr(openmod, "_load_ssm_params", fake_load_ssm_params)


class _FakeStore:
    def __init__(self, *, initial_state) -> None:
        self._state = initial_state
        self._etag = "etag-1"
        self.writes: List[Any] = []

    def read(self):
        return self._state, self._etag

    def write(self, state, if_match=None):  # noqa: ARG002
        # Track last written state (by reference for inspection)
        self.writes.append(state)
        self._state = state
        self._etag = "etag-" + str(len(self.writes) + 1)
        return self._etag


class _FakeAV:
    def __init__(self, *_args, **_kwargs) -> None:
        self.plan: Dict[str, Optional[list[Any]]] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    # Open runner uses .daily (descending newest-first)
    def daily(self, symbol: str, *, adjusted: bool = True, outputsize: str = "compact"):  # noqa: ARG002
        return self.plan.get(symbol)


class _FakeTG:
    def __init__(self, *_args, **_kwargs) -> None:
        self.sent: List[Dict[str, Any]] = []
        self.raise_on_send: bool = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def send_message(self, *, chat_id, text: str, **_kwargs):
        if self.raise_on_send:
            from common.telegram import TelegramError

            raise TelegramError("fail")
        self.sent.append({"chat_id": chat_id, "text": text})
        return {"message_id": 1}


def _patch_clients(monkeypatch: pytest.MonkeyPatch, *, store: _FakeStore, av: _FakeAV, tg: _FakeTG, atr_prev: Optional[float]) -> None:
    from open import handler as openmod

    # Patch S3StateStore to return our fake instance
    monkeypatch.setattr(openmod, "S3StateStore", lambda **_kw: store)

    # Patch AlphaVantageClient and TelegramClient to our fakes
    monkeypatch.setattr(openmod, "AlphaVantageClient", lambda *_a, **_k: av)
    monkeypatch.setattr(openmod, "TelegramClient", lambda *_a, **_k: tg)

    # Patch compute_indicators to provide ATR at the previous day index
    def fake_compute_indicators(candles_asc):
        # We expect two candles in ascending order after the handler reverses AV's output
        n = len(candles_asc)
        atr = [None] * n
        if n >= 1:
            atr[0] = atr_prev
        return SimpleNamespace(atr14=atr)

    monkeypatch.setattr(openmod, "compute_indicators", fake_compute_indicators)


def _make_two_day_series(prev_day: date, prev_close: float, open_day: date, open_open: float):
    from common.alpha_vantage import Candle

    # Build two candles (we only need fields used by the open runner)
    prev = Candle(ts=prev_day, open=prev_close, high=prev_close, low=prev_close, close=prev_close, volume=1)
    today = Candle(ts=open_day, open=open_open, high=open_open, low=open_open, close=open_open, volume=1)
    # Alpha Vantage client returns newest-first (descending)
    return [today, prev]


def test_open_no_prior_candidates_skips_all(monkeypatch: pytest.MonkeyPatch):
    from open import handler as openmod
    from state.models import State

    _patch_params(monkeypatch)

    store = _FakeStore(initial_state=State(held=[], alerts_sent={}, last_update_id=None))
    av = _FakeAV()
    tg = _FakeTG()
    _patch_clients(monkeypatch, store=store, av=av, tg=tg, atr_prev=None)

    out = openmod.run_once()

    assert out["updates"] == 0
    assert len(tg.sent) == 0
    # No writes to state
    assert store.writes == []


def test_open_excessive_gap_triggers_hold_update_and_dedup(monkeypatch: pytest.MonkeyPatch):
    from open import handler as openmod
    from state.models import State

    _patch_params(monkeypatch)

    # Seed with prior BUY_CANDIDATE on 2024-09-03
    key_buy = "AAPL:2024-09-03:BUY_CANDIDATE"
    store = _FakeStore(initial_state=State(held=[], alerts_sent={key_buy: True}, last_update_id=None))
    av = _FakeAV()
    # Set open day gap above threshold: prev_close=100, atr_prev=2.0 -> threshold=102, open=104
    av.plan = {
        "AAPL": _make_two_day_series(date(2024, 9, 3), 100.0, date(2024, 9, 4), 104.0)
    }
    tg = _FakeTG()
    _patch_clients(monkeypatch, store=store, av=av, tg=tg, atr_prev=2.0)

    out = openmod.run_once()

    assert out["updates"] == 1
    assert len(tg.sent) == 1
    msg = tg.sent[0]["text"]
    assert "OPEN UPDATE" in msg
    assert "Gap filter triggered" in msg
    assert "Threshold: $102.00" in msg
    assert "Prev close (2024-09-03): $100.00" in msg
    assert "Today open (2024-09-04): $104.00" in msg

    # Dedup key written for the open day
    state_after = store.writes[-1]
    assert state_after.alerts_sent.get("AAPL:2024-09-04:OPEN_UPDATE") is True


def test_open_normal_gap_sends_base_entry_update(monkeypatch: pytest.MonkeyPatch):
    from open import handler as openmod
    from state.models import State

    _patch_params(monkeypatch)

    key_buy = "MSFT:2024-09-03:BUY_CANDIDATE"
    store = _FakeStore(initial_state=State(held=[], alerts_sent={key_buy: True}, last_update_id=None))
    av = _FakeAV()
    # prev_close=100, atr_prev=2.0 -> threshold=102, open=101 (below threshold)
    av.plan = {
        "MSFT": _make_two_day_series(date(2024, 9, 3), 100.0, date(2024, 9, 4), 101.0)
    }
    tg = _FakeTG()
    _patch_clients(monkeypatch, store=store, av=av, tg=tg, atr_prev=2.0)

    out = openmod.run_once()

    assert out["updates"] == 1
    assert len(tg.sent) == 1
    msg = tg.sent[0]["text"]
    assert "Normal open: base entry allowed per plan." in msg
    assert "Threshold: $102.00" in msg


def test_open_dedup_skips_second_send(monkeypatch: pytest.MonkeyPatch):
    from open import handler as openmod
    from state.models import State

    _patch_params(monkeypatch)

    # Prior BUY_CANDIDATE and already sent OPEN_UPDATE for 2024-09-04
    key_buy = "NVDA:2024-09-03:BUY_CANDIDATE"
    key_open = "NVDA:2024-09-04:OPEN_UPDATE"
    store = _FakeStore(initial_state=State(held=[], alerts_sent={key_buy: True, key_open: True}, last_update_id=None))
    av = _FakeAV()
    av.plan = {
        "NVDA": _make_two_day_series(date(2024, 9, 3), 100.0, date(2024, 9, 4), 104.0)
    }
    tg = _FakeTG()
    _patch_clients(monkeypatch, store=store, av=av, tg=tg, atr_prev=2.0)

    out = openmod.run_once()

    assert out["updates"] == 0
    assert len(tg.sent) == 0


def test_open_send_error_does_not_mark_dedup(monkeypatch: pytest.MonkeyPatch):
    from open import handler as openmod
    from state.models import State

    _patch_params(monkeypatch)

    key_buy = "AMD:2024-09-03:BUY_CANDIDATE"
    store = _FakeStore(initial_state=State(held=[], alerts_sent={key_buy: True}, last_update_id=None))
    av = _FakeAV()
    av.plan = {
        "AMD": _make_two_day_series(date(2024, 9, 3), 100.0, date(2024, 9, 4), 104.0)
    }
    tg = _FakeTG()
    tg.raise_on_send = True
    _patch_clients(monkeypatch, store=store, av=av, tg=tg, atr_prev=2.0)

    out = openmod.run_once()

    assert out["updates"] == 0
    # Ensure OPEN_UPDATE not added on failure
    if store.writes:
        assert store.writes[-1].alerts_sent.get("AMD:2024-09-04:OPEN_UPDATE") is None


def test_open_whitelist_blocks_outbound_when_not_whitelisted(monkeypatch: pytest.MonkeyPatch):
    from open import handler as openmod

    # Configure whitelist that does NOT include the target chat id (123456)
    _patch_params_with_whitelist(monkeypatch, allowed_value="789")

    out = openmod.run_once()

    assert out["ok"] is True
    assert out["checked"] == 0
    assert out["updates"] == 0
    assert out.get("note") == "telegram_chat_id not in allowed_chat_ids; skipped"
