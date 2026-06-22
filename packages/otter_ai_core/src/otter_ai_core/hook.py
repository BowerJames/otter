"""Generic async hook type used by provider packages.

A :data:`Hook` is a single-argument async callback: it receives an event
describing what happened and returns an optional result whose meaning is
defined by the specific hook (e.g. a replacement value, or ``None`` for
"no change / observe-only"). Provider packages define concrete event
types and hook aliases on top of it (e.g. ``OnPayloadHook``,
``OnResponseHook``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

#: A single-argument async callback. ``[TEvent] -> Awaitable[TResponse]``.
#:
#: ``TResponse`` is hook-specific: a mutator hook returns a replacement value
#: (or ``None`` to keep the original); an observer hook returns ``None``.
type Hook[TEvent, TResponse] = Callable[[TEvent], Awaitable[TResponse]]
