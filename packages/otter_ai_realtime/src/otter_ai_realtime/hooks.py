"""Hook types for the realtime connection.

Mirrors :mod:`otter_ai_chat_completions.hooks`, expressed on top of
:data:`otter_ai_core.Hook`:

* :data:`OnSessionUpdateHook` — **mutator**. Fires after the
  ``session.update`` body is fully built and before it is sent. A
  non-``None`` return **replaces** the body; ``None`` keeps the original.
* :data:`OnConnectHook` — **observer**. Fires after the WebSocket handshake
  succeeds and before the opening ``session.update`` is sent, with a narrow
  ``{url}`` view. Returns ``None``; the return value is ignored. The WS
  handle is NOT exposed (it is owned by the transport pump).

Hook events carry the inner :class:`RealtimeModel` (the hooks are unary, per
:data:`otter_ai_core.Hook`), so a hook is reusable across models.

Hooks are async-only. Runtime containers here are :class:`dataclasses`, not
Pydantic models — they hold callables and are not serializable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from otter_ai_core import Hook
from otter_ai_realtime.models import RealtimeModel

#: Opaque realtime ``session.update`` body (the ``session`` object).
SessionUpdate = dict[str, Any]


@dataclass
class OnSessionUpdateEvent:
    """Trigger for :data:`OnSessionUpdateHook`: the fully-built session body."""

    session: SessionUpdate
    model: RealtimeModel


@dataclass
class OnConnectEvent:
    """Trigger for :data:`OnConnectHook`: a narrow view of the opened socket.

    The WebSocket handle itself is NOT exposed — it is owned by the transport
    pump and never crosses into caller/hook code.
    """

    url: str
    model: RealtimeModel


#: Mutator hook: non-``None`` return replaces the ``session.update`` body.
type OnSessionUpdateHook = Hook[OnSessionUpdateEvent, SessionUpdate | None]

#: Observer hook: the return value is ignored.
type OnConnectHook = Hook[OnConnectEvent, None]


@dataclass
class RealtimeHooks:
    """Optional callbacks invoked by the connection around its lifecycle.

    Both default to ``None`` (no-op). The connection awaits ``on_connect``
    after the WS handshake and ``on_session_update`` before sending the
    opening ``session.update``.
    """

    on_session_update: OnSessionUpdateHook | None = None
    on_connect: OnConnectHook | None = None
