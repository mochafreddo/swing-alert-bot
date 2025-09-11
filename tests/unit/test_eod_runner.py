from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest


def _patch_params(monkeypatch: pytest.MonkeyPatch, *, watchlist: Optional[str] = None) -> None:
    # Replace SSM loader with a static dict to avoid boto3
    from eod import handler as eod

    def fake_load_ssm_params(prefix: str, names: list[str]) -> Dict[str, Optional[str]]:  # noqa: ARG001
        out: Dict[str, Optional[str]] = {
            "alpha_vantage_api_key": "DUMMY-AV",
            "telegram_bot_token": "DUMMY-TG",
            "telegram_chat_id": "123456",
            "fernet_key": "A" * 43,  # not used in test path (store mocked)
            "watchlist": watchlist,
        }
        return out

    monkeypatch.setenv("STATE_BUCKET", "test-bucket")
    monkeypatch.setenv("STATE_KEY", "state.json")
    monkeypatch.setenv("PARAM_PREFIX", "/swing/dev/")
    monkeypatch.setattr(eod, "_load_ssm_params", fake_load_ssm_params)


def _patch_params_with_whitelist(
    monkeypatch: pytest.MonkeyPatch,
    *,
    watchlist: Optional[str] = None,
    allowed_value: str,
) -> None:
    # SSM loader returning whitelist that does NOT include the configured chat id
    from eod import handler as eod

    def fake_load_ssm_params(prefix: str, names: list[str]) -> Dict[str, Optional[str]]:  # noqa: ARG001
        return {
            "alpha_vantage_api_key": "DUMMY-AV",
            "telegram_bot_token": "DUMMY-TG",
            "telegram_chat_id": "123456",
            "fernet_key": "A" * 43,
            "watchlist": watchlist,
            "allowed_chat_ids": allowed_value,
        }

    monkeypatch.setenv("STATE_BUCKET", "test-bucket")
    monkeypatch.setenv("STATE_KEY", "state.json")
    monkeypatch.setenv("PARAM_PREFIX", "/swing/dev/")
    monkeypatch.setattr(eod, "_load_ssm_params", fake_load_ssm_params)


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
        self.calls: List[tuple[str, bool]] = []
        self.plan: Dict[str, Optional[list[Any]]] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def daily_if_changed(self, symbol: str, *, adjusted: bool = True, outputsize: str = "compact", cache=None):  # noqa: ARG002
        self.calls.append((symbol, adjusted))
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


def _patch_clients(monkeypatch: pytest.MonkeyPatch, *, store: _FakeStore, av: _FakeAV, tg: _FakeTG) -> None:
    from eod import handler as eod

    # Patch S3StateStore to return our fake instance
    monkeypatch.setattr(eod, "S3StateStore", lambda **_kw: store)

    # Patch AlphaVantageClient and TelegramClient to our fakes
    monkeypatch.setattr(eod, "AlphaVantageClient", lambda *_a, **_k: av)
    monkeypatch.setattr(eod, "TelegramClient", lambda *_a, **_k: tg)

    # Patch compute_indicators and evaluate_long_candidate to minimal stubs
    def fake_compute_indicators(_candles):
        # Minimal series object with latest close and ATR
        return SimpleNamespace(
            dates=[date(2024, 9, 3)],
            closes=[100.0],
            atr14=[2.0],
        )

    def fake_eval_long_candidate(symbol, series):  # noqa: ARG001
        # Always return an OK candidate dated to the series last date
        return SimpleNamespace(
            date=series.dates[-1],
            symbol=symbol,
            above_sma200=True,
            golden_cross_20_50=True,
            rsi_recross_above_30=True,
            ok=lambda: True,
        )

    monkeypatch.setattr(eod, "compute_indicators", fake_compute_indicators)
    monkeypatch.setattr(eod, "evaluate_long_candidate", fake_eval_long_candidate)


def _make_candles():
    from common.alpha_vantage import Candle

    return [
        Candle(ts=date(2024, 9, 3), open=99.0, high=101.0, low=98.0, close=100.0, volume=1_000_000),
    ]


def test_eod_empty_universe_skips_all(monkeypatch: pytest.MonkeyPatch):
    from eod import handler as eod
    from state.models import State

    _patch_params(monkeypatch, watchlist="")

    store = _FakeStore(initial_state=State(held=[], alerts_sent={}, last_update_id=None))
    av = _FakeAV()
    tg = _FakeTG()
    _patch_clients(monkeypatch, store=store, av=av, tg=tg)

    out = eod.run_once()

    assert out["scanned"] == 0
    assert out["alerts"] == 0
    assert len(av.calls) == 0
    assert len(tg.sent) == 0
    # No writes to state
    assert store.writes == []


def test_eod_candidate_triggers_alert_and_dedup(monkeypatch: pytest.MonkeyPatch):
    from eod import handler as eod
    from state.models import State

    _patch_params(monkeypatch, watchlist="AAPL")

    store = _FakeStore(initial_state=State(held=[], alerts_sent={}, last_update_id=None))
    av = _FakeAV()
    av.plan["AAPL"] = _make_candles()  # changed today
    tg = _FakeTG()
    _patch_clients(monkeypatch, store=store, av=av, tg=tg)

    out = eod.run_once()

    assert out["scanned"] == 1
    assert out["changed"] == 1
    assert out["candidates"] == 1
    assert out["alerts"] == 1
    assert len(tg.sent) == 1
    assert "BUY CANDIDATE" in tg.sent[0]["text"]

    # Dedup key written
    state_after = store.writes[-1]
    assert any(k.startswith("AAPL:2024-09-03:BUY_CANDIDATE") for k in state_after.alerts_sent.keys())


def test_eod_dedup_skips_alert(monkeypatch: pytest.MonkeyPatch):
    from eod import handler as eod
    from state.models import State

    _patch_params(monkeypatch, watchlist="AAPL")

    # Seed state with existing dedup key
    key = "AAPL:2024-09-03:BUY_CANDIDATE"
    store = _FakeStore(initial_state=State(held=[], alerts_sent={key: True}, last_update_id=None))
    av = _FakeAV()
    av.plan["AAPL"] = _make_candles()
    tg = _FakeTG()
    _patch_clients(monkeypatch, store=store, av=av, tg=tg)

    out = eod.run_once()

    assert out["alerts"] == 0
    assert len(tg.sent) == 0
    # State should remain with same key; still one write due to attempted update
    assert store.writes[-1].alerts_sent.get(key) is True


def test_eod_no_change_skips_symbol(monkeypatch: pytest.MonkeyPatch):
    from eod import handler as eod
    from state.models import State

    _patch_params(monkeypatch, watchlist="MSFT")

    store = _FakeStore(initial_state=State(held=[], alerts_sent={}, last_update_id=None))
    av = _FakeAV()
    av.plan["MSFT"] = None  # unchanged → skip
    tg = _FakeTG()
    _patch_clients(monkeypatch, store=store, av=av, tg=tg)

    out = eod.run_once()

    assert out["scanned"] == 1
    assert out["changed"] == 0
    assert out["alerts"] == 0
    assert len(tg.sent) == 0


def test_eod_send_error_does_not_mark_dedup(monkeypatch: pytest.MonkeyPatch):
    from eod import handler as eod
    from state.models import State

    _patch_params(monkeypatch, watchlist="NVDA")

    store = _FakeStore(initial_state=State(held=[], alerts_sent={}, last_update_id=None))
    av = _FakeAV()
    av.plan["NVDA"] = _make_candles()
    tg = _FakeTG()
    tg.raise_on_send = True
    _patch_clients(monkeypatch, store=store, av=av, tg=tg)

    out = eod.run_once()

    assert out["alerts"] == 0
    # No dedup written because send failed
    if store.writes:
        assert not any(k.startswith("NVDA:2024-09-03:BUY_CANDIDATE") for k in store.writes[-1].alerts_sent.keys())


def test_eod_whitelist_blocks_outbound_when_not_whitelisted(monkeypatch: pytest.MonkeyPatch):
    from eod import handler as eod

    # Configure whitelist that does NOT include the target chat id (123456)
    _patch_params_with_whitelist(monkeypatch, watchlist="AAPL", allowed_value="789")

    out = eod.run_once()

    assert out["ok"] is True
    assert out["scanned"] == 0
    assert out["changed"] == 0
    assert out["candidates"] == 0
    assert out["alerts"] == 0
    assert out.get("note") == "telegram_chat_id not in allowed_chat_ids; skipped"
