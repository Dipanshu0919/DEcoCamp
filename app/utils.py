"""
SahyogSutra Utilities Module.
Provides bounded in-memory rate limiting and template formatting helpers.
"""

import datetime
import time
from typing import Tuple, Dict, Any

# Bounded in-memory store for rate limiting (max 1000 entries)
_rate_limits: Dict[str, float] = {}
_MAX_RATE_LIMIT_ENTRIES = 1000


def check_rate_limit(key: str, window_seconds: int = 60) -> Tuple[bool, int]:
    """
    Returns (is_allowed, wait_seconds).
    Prunes expired entries on every check to ensure memory never leaks.
    """
    global _rate_limits
    now = time.time()

    # Fast prune if store grows large
    if len(_rate_limits) > _MAX_RATE_LIMIT_ENTRIES:
        _rate_limits = {k: v for k, v in _rate_limits.items() if now - v < window_seconds * 2}

    last_time = _rate_limits.get(key)
    if last_time:
        elapsed = now - last_time
        if elapsed < window_seconds:
            wait = int(window_seconds - elapsed)
            return False, wait

    _rate_limits[key] = now
    return True, 0


def datetimeformat(value: Any) -> Any:
    """Formats YYYY-MM-DD into human-readable DD Month YYYY."""
    if isinstance(value, str):
        try:
            return datetime.datetime.strptime(value, "%Y-%m-%d").strftime("%d %B %Y")
        except Exception:
            return value
    return value
