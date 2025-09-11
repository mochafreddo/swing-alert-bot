from __future__ import annotations

import json
from typing import Optional, Set, Union, List


Allowed = Set[Union[int, str]]


def parse_allowed_chat_ids(raw: Optional[str]) -> Allowed:
    """Parse allowed chat ids from CSV or JSON array.

    Accepts either:
    - JSON array: e.g., "[12345, -67890, \"@mychannel\"]"
    - CSV (commas/newlines/spaces treated as separators): "12345, -67890, @mychannel"

    Returns a set of chat identifiers (ints for numeric ids, str otherwise).
    Empty or invalid input yields an empty set.
    """
    if not raw or not isinstance(raw, str):
        return set()

    # Try JSON first
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            out: Allowed = set()
            for item in data:
                if isinstance(item, bool):
                    continue
                if isinstance(item, int):
                    out.add(int(item))
                elif isinstance(item, float):
                    if float(item).is_integer():
                        out.add(int(item))
                elif isinstance(item, str):
                    s = item.strip()
                    if s:
                        try:
                            out.add(int(s))
                        except Exception:
                            out.add(s)
            return out
    except Exception:
        pass

    # Fallback to CSV parsing; split on commas/newlines/spaces
    norm = raw.replace("\n", ",").replace(" ", ",")
    items: List[str] = [tok.strip() for tok in norm.split(",") if tok.strip()]
    out2: Allowed = set()
    for tok in items:
        if (tok.startswith('"') and tok.endswith('"')) or (tok.startswith("'") and tok.endswith("'")):
            tok = tok[1:-1]
        try:
            out2.add(int(tok))
        except Exception:
            out2.add(tok)
    return out2


def _norm_handle(s: str) -> str:
    return s.strip().lstrip("@").lower()


def is_chat_allowed(chat: dict, allowed: Allowed) -> bool:
    """Return True if the Telegram chat is allowed per whitelist.

    Rules:
    - If `allowed` is empty, treat as no whitelist (allow all).
    - Allow if chat.id (int) is in allowed.
    - Also allow if chat.username matches any string in allowed (case-insensitive),
      with or without leading '@'.
    """
    if not allowed:
        return True

    try:
        chat_id = chat.get("id") if isinstance(chat, dict) else None
    except Exception:
        chat_id = None
    if isinstance(chat_id, int) and chat_id in allowed:
        return True

    try:
        username = chat.get("username") if isinstance(chat, dict) else None
    except Exception:
        username = None
    if isinstance(username, str) and username:
        allowed_usernames = { _norm_handle(s) for s in allowed if isinstance(s, str) }
        if _norm_handle(username) in allowed_usernames:
            return True

    return False


def is_target_allowed(target: Union[int, str], allowed: Allowed) -> bool:
    """Return True if a target chat identifier is allowed per whitelist.

    - If `allowed` is empty, allow all (no whitelist configured).
    - If target is int, check membership in allowed ints.
    - If target is str, allow if numeric form matches any int in allowed, or
      if normalized handle (lowercased, without '@') matches any allowed string.
    """
    if not allowed:
        return True

    if isinstance(target, int):
        return target in allowed

    # If it's a string, try numeric coercion first
    if isinstance(target, str):
        try:
            ti = int(target)
            return ti in allowed
        except Exception:
            pass
        allowed_usernames = { _norm_handle(s) for s in allowed if isinstance(s, str) }
        return _norm_handle(target) in allowed_usernames

    return False

