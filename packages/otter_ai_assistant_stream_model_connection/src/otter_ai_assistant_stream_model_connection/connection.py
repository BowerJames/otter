"""The ``ModelConnectionFnBuilder[AssistantMessageStreamFn]`` seam.

:func:`create_assistant_stream_model_connection` is a concrete implementation
of :data:`otter_ai_core.model_connection.ModelConnectionFnBuilder` whose
``TOptions`` is an
:data:`~otter_ai_core.assistant_message_stream.AssistantMessageStreamFn`.
It is a **pure-local adapter**: it wraps any assistant-stream producer (e.g. a
chat-completions stream or a provider-stream dispatch) as a fully-functional,
request-driven, multi-turn
:class:`~otter_ai_core.model_connection.ModelConnection` — no transport,
provider, registry, or dispatch.

Why
---
A provider that can already produce an
:data:`~otter_ai_core.assistant_message_stream.AssistantMessageStream` per turn
can be surfaced through the *connection* protocol (the bidirectional peer of
the stream protocol) without speaking a realtime wire format. Callers iterate
one inbound :data:`~otter_ai_core.model_connection.ServerEvent` stream and send
:class:`~otter_ai_core.model_connection.ClientEvent` s to drive generations,
exactly as they would against a Realtime connection — but the backend is the
supplied ``stream_fn`` running locally.

The seam is a **builder**: it closes over ``stream_fn`` (the only "option") and
returns an :data:`~otter_ai_core.model_connection.ModelConnectionFn` (the
options-bound producer). That producer is **synchronous**: it returns the
:class:`~otter_ai_core.model_connection.ModelConnection` immediately and spawns
its backend via :func:`asyncio.create_task`. The producer **never raises** — a
defensive failure is encoded as a
:class:`~otter_ai_core.model_connection.ConnectionErrorEvent` on the returned
connection (the wrapped producer is itself contractually never-raising).

Driver semantics
----------------
* **Request-driven / multi-turn.** The backend idles, draining client events.
  On a :class:`~otter_ai_core.model_connection.ResponseCreate` it invokes
  ``stream_fn(context, per_response_abort)`` once for that turn and forwards
  the translated :class:`~otter_ai_core.model_connection.ServerEvent` s. A
  subsequent ``ResponseCreate`` (after the turn ends) starts the next
  generation. Concurrent responses are not supported (v1).
* **Live context.** A client
  :class:`~otter_ai_core.model_connection.ContextItemAddEvent` appends to the
  caller's passed-in :class:`~otter_ai_core.Context` (mutated in place) and
  echoes a :class:`~otter_ai_core.model_connection.ContextItemAddedEvent`. On a
  clean ``AssistantDoneEvent`` the final message is auto-appended as an
  :class:`~otter_ai_core.AssistantContextItem` (uuid4 id) and announced
  (see :mod:`._translate`).
* **Per-response abort.** A client
  :class:`~otter_ai_core.model_connection.AbortResponseEvent` aborts **only**
  the in-flight response (via a fresh ``per_response_abort``
  :class:`asyncio.Event` passed into ``stream_fn``); the connection stays open
  for further generations. The producer is contractually expected to honour the
  abort signal and terminate the stream with an aborted terminal event.
* **Connection cancel.** The producer's required ``abort`` argument is a
  *connection*-level cancel: setting it aborts any in-flight response and ends
  the connection gracefully (**no** ``ConnectionErrorEvent``). Caller
  ``close()`` behaves identically.

The backend holds at most one outstanding ``anext`` on each of the stream and
the outbound client channel at any time (both are single-consumer). During a
response it races three concerns — the stream, the client channel, and the
connection abort — generalising :func:`otter_ai_realtime._transport.pump`'s
first-wins pattern.
"""

from __future__ import annotations

import asyncio
from typing import Any

from otter_ai_core import Context, create_connection
from otter_ai_core.assistant_message_stream import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantMessageStream,
    AssistantMessageStreamFn,
)
from otter_ai_core.connection import ConnectionBackend
from otter_ai_core.model_connection import (
    ClientEvent,
    ConnectionErrorEvent,
    ContextItemAddedEvent,
    ContextItemAddEvent,
    ModelConnection,
    ModelConnectionFn,
    ResponseCreate,
    ServerEvent,
)

from ._translate import translate

#: Strong references to in-flight backend tasks. asyncio will cancel a task
#: with no live reference before it completes; we hold one until the backend
#: finishes. (Mirrors the chat-completions ``_producer_tasks`` /
#: realtime ``_tasks`` sets.)
_tasks: set[asyncio.Task[None]] = set()


def create_assistant_stream_model_connection(
    stream_fn: AssistantMessageStreamFn,
) -> ModelConnectionFn:
    """Build a :class:`~otter_ai_core.model_connection.ModelConnectionFn` that
    drives the supplied assistant-stream producer for every generation.

    A concrete value of
    :data:`~otter_ai_core.model_connection.ModelConnectionFnBuilder`: closes
    over ``stream_fn`` and returns the options-bound producer. The returned
    producer is synchronous — it returns the
    :class:`~otter_ai_core.model_connection.ModelConnection` immediately and
    spawns its backend via :func:`asyncio.create_task` — and honours the
    builder contract: it never raises.
    """

    def connection_fn(context: Context, abort: asyncio.Event) -> ModelConnection:
        conn: ModelConnection
        backend: ConnectionBackend[ClientEvent, ServerEvent]
        conn, backend = create_connection()
        task = asyncio.create_task(_run(backend, stream_fn, context, abort))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return conn

    return connection_fn


# --------------------------------------------------------------------------- #
# Backend task
# --------------------------------------------------------------------------- #


async def _run(
    backend: ConnectionBackend[ClientEvent, ServerEvent],
    stream_fn: AssistantMessageStreamFn,
    context: Context,
    abort: asyncio.Event,
) -> None:
    try:
        await _drive(backend, stream_fn, context, abort)
    except Exception as exc:  # noqa: BLE001 — the seam must never raise.
        # A defensive catch only: the wrapped producer encodes its own failures
        # as terminal stream events, and the driver is written not to raise.
        # Anything that escapes is surfaced as a connection-level error unless
        # the connection was already being cancelled.
        if not abort.is_set():
            backend.push(_connection_error(exc))
    finally:
        backend.end()


async def _drive(
    backend: ConnectionBackend[ClientEvent, ServerEvent],
    stream_fn: AssistantMessageStreamFn,
    context: Context,
    abort: asyncio.Event,
) -> None:
    """Idle loop: drain client events, dispatching ``ResponseCreate`` to a turn.

    ``abort`` is priority-checked every iteration *before* any blocking wait:
    if the connection is being cancelled, we tear down immediately even when a
    client event is also pending. (An earlier draft filtered already-done tasks
    out of the wait set, which made a set-but-unhandled ``abort`` block forever
    on the still-pending client channel.)
    """
    client_task = asyncio.create_task(_anext_or_none(backend))
    abort_task = asyncio.create_task(abort.wait())
    try:
        while True:
            if abort_task.done():
                return  # connection-level cancel — graceful (priority).
            if client_task.done():
                client_event = client_task.result()
                if client_event is None:
                    # Caller closed the connection — graceful teardown.
                    return
                # NOTE: ``client_task`` is intentionally NOT refreshed until
                # the turn ends. ``_run_response`` owns the sole outstanding
                # ``anext(backend)`` during a turn — the backend's outbound
                # side is single-consumer, so a second concurrent ``anext``
                # would race on the queue. The idle loop resumes draining only
                # once the turn ends.
                connection_ended = await _handle_idle_client_event(
                    backend, stream_fn, context, abort, client_event
                )
                # If the turn ended because the caller closed / the connection
                # was aborted, the outbound stream is already exhausted — do
                # NOT start another ``anext`` on it (the single termination
                # sentinel has been consumed).
                if connection_ended:
                    return
                client_task = asyncio.create_task(_anext_or_none(backend))
                continue
            # Nothing complete yet — block until one of the two fires.
            await asyncio.wait(
                {client_task, abort_task}, return_when=asyncio.FIRST_COMPLETED
            )
    finally:
        for task in (client_task, abort_task):
            if not task.done():
                task.cancel()
        for task in (client_task, abort_task):
            await _suppress(task)


async def _handle_idle_client_event(
    backend: ConnectionBackend[ClientEvent, ServerEvent],
    stream_fn: AssistantMessageStreamFn,
    context: Context,
    abort: asyncio.Event,
    client_event: ClientEvent,
) -> bool:
    """Dispatch one idle client event.

    Returns ``True`` if the connection has ended (the turn observed a caller
    close or connection abort) and the idle loop must stop.
    """
    if isinstance(client_event, ResponseCreate):
        return await _run_response(backend, stream_fn, context, abort)
    if isinstance(client_event, ContextItemAddEvent):
        _accept_context_item(backend, context, client_event)
    # AbortResponseEvent outside a response is a no-op; the connection stays
    # open for the next ``ResponseCreate``.
    return False


def _accept_context_item(
    backend: ConnectionBackend[ClientEvent, ServerEvent],
    context: Context,
    client_event: ContextItemAddEvent,
) -> None:
    """Append a caller-supplied item to the live context and echo it back."""
    item = client_event.item
    context.items.append(item)
    backend.push(
        ContextItemAddedEvent(
            type="context_item.added",
            # The caller supplies the id for its own items (vs the uuid4 the
            # server generates for committed assistant turns).
            item_id=item.id,
            role=item.role,
            item=item,
        )
    )


# --------------------------------------------------------------------------- #
# Per-response driver
# --------------------------------------------------------------------------- #


async def _run_response(
    backend: ConnectionBackend[ClientEvent, ServerEvent],
    stream_fn: AssistantMessageStreamFn,
    context: Context,
    abort: asyncio.Event,
) -> bool:
    """Drive one assistant turn, racing the stream against client + abort.

    Returns ``True`` if the connection has ended (caller closed or connection
    aborted) — in which case the caller's outbound stream is already exhausted
    and :func:`_drive` must **not** start another ``anext`` on it (the single
    termination sentinel has been consumed). Returns ``False`` when the turn
    ended normally and the idle loop should resume draining.

    A fresh ``per_response_abort`` is passed into ``stream_fn`` for each turn.
    Client events are handled inline: an ``AbortResponseEvent`` flips
    ``per_response_abort`` (and keeps the connection open); a
    ``ContextItemAddEvent`` is committed immediately; caller ``close()`` or a
    connection abort both flip ``per_response_abort`` and let the stream drain
    to its (aborted) terminal. Further ``ResponseCreate`` events arriving while
    a turn is in flight are ignored (v1: no concurrent responses).
    """
    per_response_abort = asyncio.Event()
    stream: AssistantMessageStream = stream_fn(context, per_response_abort)
    connection_ended = False

    # All three concerns are long-lived tasks, created once and recreated ONLY
    # when one completes. The stream and the backend's outbound side are both
    # single-consumer, so at most one outstanding ``anext`` may be in flight on
    # each at any time — recreating a task unconditionally each iteration (as
    # an earlier draft did) would spin up a second ``anext`` while the first is
    # still pending, leaking it and deadlocking the queue.
    stream_task: asyncio.Task[AssistantMessageEvent | None] = asyncio.create_task(
        _anext_or_none(stream)
    )
    client_task: asyncio.Task[ClientEvent | None] | None = asyncio.create_task(
        _anext_or_none(backend)
    )
    abort_task: asyncio.Task[Any] | None = asyncio.create_task(abort.wait())
    terminal = False

    try:
        while not terminal:
            await asyncio.wait(
                {
                    task
                    for task in (stream_task, client_task, abort_task)
                    if task is not None and not task.done()
                },
                return_when=asyncio.FIRST_COMPLETED,
            )

            # 1. Stream event — translate + push; detect terminal. Recreate
            #    the stream anext only because it just completed.
            if stream_task.done():
                aevent = stream_task.result()
                if aevent is None:
                    # Stream ended without a recognised terminal (shouldn't
                    # happen for a conforming producer); stop regardless.
                    terminal = True
                else:
                    for server_event in translate(aevent, context):
                        backend.push(server_event)
                    if isinstance(aevent, (AssistantDoneEvent, AssistantErrorEvent)):
                        terminal = True
                    else:
                        stream_task = asyncio.create_task(_anext_or_none(stream))

            # 2. Client event — handle inline; refresh the outstanding anext.
            #
            #    The caller-close (``None`` sentinel) branch is checked
            #    UNGUARDED by ``not terminal``: if the stream also reached a
            #    terminal event this same ``asyncio.wait`` cycle, the sentinel
            #    would otherwise go undetected, ``connection_ended`` would stay
            #    ``False``, and the idle loop would start another ``anext`` on
            #    the already-exhausted outbound stream — deadlocking forever
            #    (single-sentinel discipline). The other branches only refresh
            #    ``client_task`` while the turn is still live (``not terminal``),
            #    since starting a new ``anext`` after a terminal makes no sense.
            if client_task is not None and client_task.done():
                client_event = client_task.result()
                client_task = None
                if client_event is None:
                    # Caller closed — propagate to the stream, drain the aborted
                    # terminal, then signal the idle loop to stop (the outbound
                    # sentinel has been consumed here).
                    per_response_abort.set()
                    connection_ended = True
                elif not terminal:
                    if isinstance(client_event, ResponseCreate):
                        # v1: a concurrent response.create is ignored.
                        client_task = asyncio.create_task(_anext_or_none(backend))
                    elif isinstance(client_event, ContextItemAddEvent):
                        _accept_context_item(backend, context, client_event)
                        client_task = asyncio.create_task(_anext_or_none(backend))
                    else:
                        # AbortResponseEvent — abort only this turn.
                        per_response_abort.set()
                        client_task = asyncio.create_task(_anext_or_none(backend))

            # 3. Connection abort — propagate to the stream and drain terminal.
            if abort_task is not None and abort_task.done() and not terminal:
                abort_task = None
                per_response_abort.set()
                connection_ended = True
    finally:
        for task in (stream_task, client_task, abort_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (stream_task, client_task, abort_task):
            if task is not None:
                await _suppress(task)
    return connection_ended


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _anext_or_none(aiter: Any) -> Any:
    """``await anext(aiter)``, returning ``None`` on end-of-stream.

    Exactly one outstanding ``anext`` per channel must be in flight at a time
    (the stream and the connection's outbound side are both single-consumer).
    """
    try:
        return await anext(aiter)
    except StopAsyncIteration:
        return None


async def _suppress(task: asyncio.Task[Any]) -> None:
    """Await a task, swallowing cancellation/exceptions (best-effort cleanup)."""
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001, PERF203
        pass


def _connection_error(exc: BaseException) -> ConnectionErrorEvent:
    return ConnectionErrorEvent(
        type="connection.error",
        message=f"{type(exc).__name__}: {exc}",
        reason="transport_error",
    )


__all__ = ["create_assistant_stream_model_connection"]
