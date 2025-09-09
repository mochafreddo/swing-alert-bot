from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class State(BaseModel):
    """
    Persistent bot state serialized to JSON and encrypted at rest.

    Fields
    - held: list of ticker symbols currently marked as held (e.g., ["AAPL", "NVDA"]).
    - alerts_sent: dedup map where the key encodes a unique alert signature
      (e.g., "AAPL:2025-09-05:EMA_GC") and the value is a boolean marker.
    - last_update_id: last processed Telegram update_id for offset-based polling.

    Notes
    - This model represents the logical schema. The stored object will be the JSON
      encoding of this model, encrypted using Fernet (implemented in a separate task).
    - The exact key format for `alerts_sent` should follow the convention:
        "{TICKER}:{YYYY-MM-DD}:{ALERT_CODE}"
      where ALERT_CODE identifies the signal type (e.g., EMA_GC for EMA20>EMA50 crossover).
    """

    held: List[str] = Field(default_factory=list, description="List of held tickers")
    alerts_sent: Dict[str, bool] = Field(
        default_factory=dict,
        description="Map of alert-dedup keys to a boolean marker",
    )
    last_update_id: Optional[int] = Field(
        default=None,
        description="Last processed Telegram update_id (None if never polled)",
    )

    @classmethod
    def empty(cls) -> "State":
        """Convenience constructor for a fresh, empty state."""
        return cls()

