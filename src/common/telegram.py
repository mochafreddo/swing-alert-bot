from __future__ import annotations

import time
from typing import Any, Dict, Optional, Union

import httpx

from .rate_limiter import SlidingWindowRateLimiter, RateLimitError


DEFAULT_API_BASE = "https://api.telegram.org"


class TelegramError(RuntimeError):
    """Base error for Telegram client."""


class TelegramApiError(TelegramError):
    """API returned an error payload or unexpected structure."""


class TelegramRateLimitError(TelegramError):
    """Local or remote rate limiting prevented the request."""


class TelegramClient:
    """
    Minimal Telegram Bot API client focused on sendMessage.

    Notes
    - Uses JSON for request bodies (per Telegram Bot API docs; not for file uploads).
    - Retries transient HTTP errors and 429 with backoff, honoring `retry_after` when provided.
    - Provides a simple local QPS limiter (default conservative: 25 req/sec).
    """

    def __init__(
        self,
        token: str,
        *,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 15.0,
        max_per_second: int = 25,
        client: Optional[httpx.Client] = None,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout
        self._owns_client = client is None
        base_url = f"{self._api_base}/bot{self._token}"
        self._client = client or httpx.Client(base_url=base_url, timeout=self._timeout)
        # Conservative limiter to avoid spikes. Telegram allows high throughput,
        # but this project sends low volume anyway.
        self._limiter = SlidingWindowRateLimiter(max_calls=max_per_second, per_seconds=1.0)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TelegramClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --------------- Public API ---------------
    def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        *,
        parse_mode: Optional[str] = None,
        disable_web_page_preview: Optional[bool] = None,
        disable_notification: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        message_thread_id: Optional[int] = None,
        allow_paid_broadcast: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Send a text message via Telegram `sendMessage`.

        Returns the Message object (as dict) on success.
        Raises TelegramApiError on API errors and TelegramRateLimitError on local RL.
        """
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            payload["disable_web_page_preview"] = disable_web_page_preview
        if disable_notification is not None:
            payload["disable_notification"] = disable_notification
        if protect_content is not None:
            payload["protect_content"] = protect_content
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        if allow_paid_broadcast is not None:
            payload["allow_paid_broadcast"] = allow_paid_broadcast

        data = self._request("sendMessage", payload)
        # Expect Telegram's envelope: { ok: bool, result?: {...}, description?: str }
        if not isinstance(data, dict) or "ok" not in data:
            raise TelegramApiError("Malformed response from Telegram Bot API")
        if data.get("ok") is True and isinstance(data.get("result"), dict):
            return data["result"]  # type: ignore[return-value]
        # Error path
        desc = data.get("description") or "Telegram API error"
        code = data.get("error_code")
        raise TelegramApiError(f"{desc} (code={code})")

    # --------------- Internal ---------------
    def _request(self, method: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
        # Local throttle
        try:
            self._limiter.acquire(blocking=True)
        except RateLimitError as rl:
            raise TelegramRateLimitError("Local rate limiter prevented request") from rl

        # Retry transient HTTP and API 429 with simple backoff
        attempt = 0
        backoff = 0.5
        last_exc: Optional[Exception] = None
        while attempt < 5:
            try:
                resp = self._client.post(f"/{method}", json=json_body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
            else:
                # HTTP-level errors
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except Exception as exc:  # JSON decode error
                        raise TelegramApiError("Failed to parse JSON from Telegram API") from exc

                # Handle typical transient statuses
                if resp.status_code in (429, 500, 502, 503, 504):
                    # Try to parse retry_after from body if available
                    retry_after = None
                    try:
                        body = resp.json()
                        # Telegram 429 includes { ok:false, error_code:429, parameters: { retry_after: N } }
                        params = body.get("parameters") if isinstance(body, dict) else None
                        if isinstance(params, dict):
                            ra = params.get("retry_after")
                            if isinstance(ra, (int, float)):
                                retry_after = float(ra)
                    except Exception:
                        pass

                    delay = retry_after if retry_after is not None else backoff
                    time.sleep(min(delay, 10.0))
                    backoff = min(backoff * 2, 8.0)
                    attempt += 1
                    continue

                # Non-retryable HTTP error
                raise TelegramApiError(
                    f"HTTP {resp.status_code} from Telegram: {resp.text[:200]}"
                )

            # Transport error path
            attempt += 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

        if last_exc is not None:
            raise TelegramError("Failed request after retries") from last_exc
        raise TelegramError("Failed request after retries (unknown error)")


__all__ = [
    "TelegramClient",
    "TelegramError",
    "TelegramApiError",
    "TelegramRateLimitError",
]

