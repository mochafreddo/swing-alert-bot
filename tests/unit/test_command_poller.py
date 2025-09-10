from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest


def _patch_params(monkeypatch: pytest.MonkeyPatch) -> None:
    from poller import handler as poller

    def fake_load_ssm_params(prefix: str, names: list[str]) -> Dict[str, Optional[str]]:  # noqa: ARG001
        return {
            "telegram_bot_token": "DUMMY-TG",
            "fernet_key": "A" * 43,
        }

    monkeypatch.setenv("STATE_BUCKET", "test-bucket")
    monkeypatch.setenv("STATE_KEY", "state.json")
    monkeypatch.setenv("PARAM_PREFIX", "/swing/dev/")
    monkeypatch.setattr(poller, "_load_ssm_params", fake_load_ssm_params)


def _patch_params_with_whitelist(monkeypatch: pytest.MonkeyPatch, allowed_value: str) -> None:
    from poller import handler as poller

    def fake_load_ssm_params(prefix: str, names: list[str]):  # noqa: ARG001
        return {
            "telegram_bot_token": "DUMMY-TG",
            "fernet_key": "A" * 43,
            "allowed_chat_ids": allowed_value,
        }

    monkeypatch.setenv("STATE_BUCKET", "test-bucket")
    monkeypatch.setenv("STATE_KEY", "state.json")
    monkeypatch.setenv("PARAM_PREFIX", "/swing/dev/")
    monkeypatch.setattr(poller, "_load_ssm_params", fake_load_ssm_params)


class _FakeStore:
    def __init__(self, *, initial_state) -> None:
        self._state = initial_state
        self._etag = "etag-1"
        self.writes: List[Any] = []

    def read(self):
        return self._state, self._etag

    def write(self, state, if_match=None):  # noqa: ARG002
        self.writes.append(state)
        self._state = state
        self._etag = f"etag-{len(self.writes) + 1}"
        return self._etag


class _FakeTG:
    def __init__(self, *_args, **_kwargs) -> None:
        self._updates_plan: List[Dict[str, Any]] = []
        self.sent: List[Dict[str, Any]] = []
        self.raise_on_send: bool = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def plan_updates(self, updates: List[Dict[str, Any]]):
        self._updates_plan = updates

    def get_updates(self, *, offset=None, limit=None, timeout=None, allowed_updates=None):  # noqa: ARG002
        # Ignore params in fake; just return planned updates
        return self._updates_plan

    def send_message(self, *, chat_id, text: str, **_kwargs):
        if self.raise_on_send:
            from common.telegram import TelegramError

            raise TelegramError("fail")
        self.sent.append({"chat_id": chat_id, "text": text})
        return {"message_id": 1}


def _patch_clients(monkeypatch: pytest.MonkeyPatch, *, store: _FakeStore, tg: _FakeTG) -> None:
    from poller import handler as poller

    monkeypatch.setattr(poller, "S3StateStore", lambda **_kw: store)
    monkeypatch.setattr(poller, "TelegramClient", lambda *_a, **_k: tg)


def _mk_update(update_id: int, chat_id: int, text: str) -> Dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id * 10,
            "date": 0,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def test_process_buy_list_sell_and_advance_offset(monkeypatch: pytest.MonkeyPatch):
    from poller import handler as poller
    from state.models import State

    _patch_params(monkeypatch)

    store = _FakeStore(initial_state=State(held=[], alerts_sent={}, last_update_id=40))
    tg = _FakeTG()
    tg.plan_updates(
        [
            _mk_update(41, 123, "/buy aapl"),
            _mk_update(42, 123, "/list"),
            _mk_update(43, 123, "/sell AAPL"),
        ]
    )

    _patch_clients(monkeypatch, store=store, tg=tg)

    out = poller.run_once(allowed_updates=["message"], limit=100, timeout=0)

    assert out["ok"] is True
    assert out["received"] == 3
    assert out["new_last_update_id"] == 43
    # Verify acks sent
    assert len(tg.sent) == 3
    texts = [m["text"] for m in tg.sent]
    assert any("Marked as held" in t for t in texts)
    assert any("Held tickers" in t for t in texts)
    assert any("Unmarked" in t for t in texts)
    # Persisted last_update_id
    assert store.writes[-1].last_update_id == 43


def test_ignores_non_message_updates_and_send_errors(monkeypatch: pytest.MonkeyPatch):
    from poller import handler as poller
    from state.models import State

    _patch_params(monkeypatch)

    store = _FakeStore(initial_state=State(held=[], alerts_sent={}, last_update_id=None))
    tg = _FakeTG()
    bad_update = {"update_id": 10, "edited_message": {"message_id": 100}}
    good = _mk_update(11, 999, "/buy msft")
    tg.plan_updates([bad_update, good])
    tg.raise_on_send = True  # simulate send failure

    _patch_clients(monkeypatch, store=store, tg=tg)

    out = poller.run_once(allowed_updates=["message"], limit=100, timeout=0)

    assert out["ok"] is True
    assert out["received"] == 2
    assert out["new_last_update_id"] == 11
    # Send failed, but state should still advance last_update_id and record held change
    assert store.writes[-1].last_update_id == 11
    assert "MSFT" in store.writes[-1].held


def test_whitelist_blocks_non_allowed_and_advances_offset(monkeypatch: pytest.MonkeyPatch):
    from poller import handler as poller
    from state.models import State

    # Only allow chat id 123
    _patch_params_with_whitelist(monkeypatch, "123")

    store = _FakeStore(initial_state=State(held=[], alerts_sent={}, last_update_id=5))
    tg = _FakeTG()
    tg.plan_updates(
        [
            _mk_update(6, 999, "/buy tsla"),  # blocked
            _mk_update(7, 123, "/buy msft"),  # allowed
            _mk_update(8, 999, "/list"),      # blocked
        ]
    )

    _patch_clients(monkeypatch, store=store, tg=tg)

    out = poller.run_once(allowed_updates=["message"], limit=100, timeout=0)

    assert out["ok"] is True
    assert out["received"] == 3
    assert out["new_last_update_id"] == 8
    # Only one ACK sent (to allowed chat)
    assert len(tg.sent) == 1
    assert tg.sent[0]["chat_id"] == 123
    # State advanced and only allowed change applied
    assert store.writes[-1].last_update_id == 8
    assert "MSFT" in store.writes[-1].held
    assert "TSLA" not in store.writes[-1].held


def test_whitelist_allows_by_username(monkeypatch: pytest.MonkeyPatch):
    from poller import handler as poller
    from state.models import State

    # Allow by username (both with and without @)
    _patch_params_with_whitelist(monkeypatch, "[\"@jane\", \"jack\"]")

    store = _FakeStore(initial_state=State(held=[], alerts_sent={}, last_update_id=19))
    tg = _FakeTG()
    upd_allowed = {
        "update_id": 20,
        "message": {
            "message_id": 200,
            "date": 0,
            "chat": {"id": 777, "type": "private", "username": "Jane"},
            "text": "/buy aapl",
        },
    }
    upd_blocked = {
        "update_id": 21,
        "message": {
            "message_id": 210,
            "date": 0,
            "chat": {"id": 888, "type": "private", "username": "someoneelse"},
            "text": "/buy tsla",
        },
    }
    tg.plan_updates([upd_allowed, upd_blocked])

    _patch_clients(monkeypatch, store=store, tg=tg)

    out = poller.run_once(allowed_updates=["message"], limit=100, timeout=0)

    assert out["ok"] is True
    assert out["received"] == 2
    assert out["new_last_update_id"] == 21
    # Only one ACK sent (to allowed username)
    assert len(tg.sent) == 1
    assert tg.sent[0]["chat_id"] == 777
    # State advanced and only allowed change applied
    assert store.writes[-1].last_update_id == 21
    assert "AAPL" in store.writes[-1].held
    assert "TSLA" not in store.writes[-1].held
