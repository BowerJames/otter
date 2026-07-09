"""Internal helpers shared across agent modules."""

from __future__ import annotations

import asyncio


def now_ms() -> int:
    """Best-effort millisecond timestamp (the context model uses ms epochs).

    Uses :func:`asyncio.get_running_loop` (not the deprecated
    :func:`asyncio.get_event_loop`); only call from within a running loop.
    """
    return int(asyncio.get_running_loop().time() * 1000)
