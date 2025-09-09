from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_CACHE_DIR_ENV = "SWING_CACHE_DIR"


def _default_cache_file() -> Path:
    # Prefer explicit env var, else project-local .cache folder
    base = os.environ.get(DEFAULT_CACHE_DIR_ENV)
    if base:
        return Path(base) / "av_daily_meta.json"
    return Path(".cache") / "av_daily_meta.json"


@dataclass
class _Entry:
    last_refreshed: str  # ISO date in YYYY-MM-DD
    last_checked_at: str  # ISO 8601 timestamp with offset, e.g., "+00:00"


class SymbolUpdateCache:
    """
    Tiny JSON-based cache storing the last refreshed date per symbol/series.

    - Backed by a single JSON file: { key: {last_refreshed, last_checked_at}, ... }
    - Key format: "{SYMBOL}:{adj|raw}"
    - Intended to be durable between runs (e.g., local dev, or persisted volume).
    - Safe to use in Lambda with /tmp, but persistence across cold starts is not guaranteed.
    """

    def __init__(self, path: Optional[os.PathLike[str] | str] = None) -> None:
        self._path = Path(path) if path else _default_cache_file()
        self._data: Dict[str, Dict[str, str]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, dict):
                        # normalize to str->dict[str,str]
                        self._data = {
                            str(k): {
                                "last_refreshed": str(v.get("last_refreshed", "")),
                                "last_checked_at": str(v.get("last_checked_at", "")),
                            }
                            for k, v in raw.items()
                            if isinstance(v, dict)
                        }
        except Exception:
            # Corrupt cache: ignore and start fresh
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, sort_keys=True)
        except Exception:
            # Best-effort cache; ignore write failures
            pass

    @staticmethod
    def _key(symbol: str, *, adjusted: bool) -> str:
        return f"{symbol.upper()}:{'adj' if adjusted else 'raw'}"

    def get_last_refreshed(self, symbol: str, *, adjusted: bool) -> Optional[str]:
        self._ensure_loaded()
        entry = self._data.get(self._key(symbol, adjusted=adjusted))
        if entry:
            val = entry.get("last_refreshed")
            return val or None
        return None

    def set_last_refreshed(self, symbol: str, *, adjusted: bool, last_refreshed: str) -> None:
        self._ensure_loaded()
        # Use timezone-aware UTC; keep standard "+00:00" offset form
        dt = datetime.now(UTC)
        now = dt.isoformat(timespec="seconds")
        self._data[self._key(symbol, adjusted=adjusted)] = {
            "last_refreshed": last_refreshed,
            "last_checked_at": now,
        }
        self._save()
