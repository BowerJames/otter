"""The Realtime ``ModelConnectionFnBuilder`` seam.

:func:`create_realtime_model_connection` is a concrete implementation of
:data:`otter_ai_core.model_connection.ModelConnectionFnBuilder` (parameterised
by :class:`RealtimeModelOptions`) for OpenAI-Realtime-format APIs. It is the
bidirectional peer of
:func:`otter_ai_chat_completions.create_chat_completions_assistant_message_stream`.

The seam is a **builder**: it closes over the per-call ``options`` bundle and
returns an :data:`~otter_ai_core.model_connection.ModelConnectionFn` (the
options-bound producer). That producer is **synchronous**: it returns the
:class:`~otter_ai_core.model_connection.ModelConnection` immediately and
schedules its backend (the WebSocket pump) via :func:`asyncio.create_task`.
The backend pushes every inbound server event (including the terminal ones),
then calls ``end()`` on the inbound writer. The producer **never raises** —
connect/handshake/transport failures are encoded as a
:class:`~otter_ai_core.model_connection.ConnectionErrorEvent` on the returned
connection.

Cooperative cancellation is honoured via the ``abort`` argument (an
:class:`asyncio.Event`): setting it tears down the WebSocket and ends the
inbound stream gracefully (no error event) — it is a *connection* cancel, not
a per-response abort. Per-response abort is driven by the caller pushing an
:class:`~otter_ai_core.model_connection.AbortResponseEvent` onto the
connection's outbound stream, which the pump translates to ``response.cancel``.

On connect the backend performs a **full replay** of the supplied
:class:`~otter_ai_core.Context`: the system prompt becomes the opening
``session.update`` ``instructions``, the context tools become ``tools``, and
each item is sent as a ``conversation.item.create`` frame.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from otter_ai_core import Context, create_connection
from otter_ai_core.connection import ConnectionBackend
from otter_ai_core.model_connection import (
    ClientEvent,
    ModelConnection,
    ModelConnectionFn,
    ServerEvent,
)
from otter_ai_realtime import _transport
from otter_ai_realtime._events import InboundTranslator, connection_error
from otter_ai_realtime._messages import convert_items_to_create_frames
from otter_ai_realtime._session import build_session_body
from otter_ai_realtime.hooks import OnConnectEvent, OnSessionUpdateEvent
from otter_ai_realtime.options import RealtimeModelOptions

#: Strong references to in-flight backend tasks. asyncio will cancel a task
#: with no live reference before it completes; we hold one until the backend
#: finishes. (Mirrors the chat-completions ``_producer_tasks`` set.)
_tasks: set[asyncio.Task[None]] = set()


def create_realtime_model_connection(
    options: RealtimeModelOptions,
) -> ModelConnectionFn:
    """Build a :class:`~otter_ai_core.model_connection.ModelConnectionFn` for
    a Realtime model.

    A concrete value of
    :data:`~otter_ai_core.model_connection.ModelConnectionFnBuilder`: closes
    over ``options`` and returns the options-bound producer. The returned
    producer is **synchronous** — it returns the
    :class:`~otter_ai_core.model_connection.ModelConnection` immediately and
    spawns the backend (WebSocket pump) via :func:`asyncio.create_task` — and
    honours the builder contract: it never raises.

    ``abort`` (the producer's second argument) is the connection-cancel signal
    (an :class:`asyncio.Event`); it is **required** — setting it tears down the
    WebSocket and ends the inbound stream gracefully (no error event). It is a
    *connection* cancel, not a per-response abort. Per-response abort is driven
    by the caller pushing an
    :class:`~otter_ai_core.model_connection.AbortResponseEvent` onto the
    connection's outbound stream, which the pump translates to
    ``response.cancel``.
    """

    def connection_fn(context: Context, abort: asyncio.Event) -> ModelConnection:
        conn: ModelConnection
        backend: ConnectionBackend[ClientEvent, ServerEvent]
        conn, backend = create_connection()
        task = asyncio.create_task(_run(backend, options, context, abort))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return conn

    return connection_fn


# --------------------------------------------------------------------------- #
# Backend task
# --------------------------------------------------------------------------- #


async def _run(
    backend: ConnectionBackend[Any, Any],
    options: RealtimeModelOptions,
    context: Context,
    abort: asyncio.Event,
) -> None:
    model = options.model
    api_key = model.api_key
    if not api_key:
        backend.push(
            connection_error(
                f"No API key for provider: {model.provider}", "connect_failed"
            )
        )
        backend.end()
        return

    try:
        ws = await _transport.connect_ws(model, api_key)
    except Exception as exc:  # noqa: BLE001 — the seam must never raise.
        backend.push(connection_error(f"{type(exc).__name__}: {exc}", "connect_failed"))
        backend.end()
        return

    try:
        await _drive(backend, ws, options, context, abort)
    except Exception as exc:  # noqa: BLE001 — the seam must never raise.
        if not abort.is_set():
            backend.push(
                connection_error(f"{type(exc).__name__}: {exc}", "transport_error")
            )
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001 — best-effort close.
            pass
        backend.end()


async def _drive(
    backend: ConnectionBackend[Any, Any],
    ws: Any,
    options: RealtimeModelOptions,
    context: Context,
    abort: asyncio.Event,
) -> None:
    """Open-handshake (connect hook + session.update + replay) then pump."""
    model = options.model

    if options.hooks.on_connect is not None:
        await options.hooks.on_connect(
            OnConnectEvent(url=_transport.realtime_url(model), model=model)
        )

    # Build + (optionally replace) the session body, then send session.update.
    session_body = build_session_body(
        options, context.system_prompt, context.tools or []
    )
    if options.hooks.on_session_update is not None:
        replaced = await options.hooks.on_session_update(
            OnSessionUpdateEvent(session=session_body, model=model)
        )
        if replaced is not None:
            session_body = replaced
    await ws.send(json.dumps({"type": "session.update", "session": session_body}))

    # Full replay: each seeded context item becomes a conversation.item.create.
    messages = [item.to_message() for item in context.items]
    for frame in convert_items_to_create_frames(messages):
        await ws.send(json.dumps(frame))

    # Bidirectional pump owns the rest of the session.
    translator = InboundTranslator(model)
    await _transport.pump(backend, ws, abort, translator)


__all__ = ["create_realtime_model_connection"]
