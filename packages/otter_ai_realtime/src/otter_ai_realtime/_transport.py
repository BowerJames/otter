"""WebSocket transport: connect + bidirectional pump.

:func:`connect_ws` opens the WebSocket (tests monkeypatch this, exactly as the
chat-completions tests monkeypatch ``_create_client``). :func:`pump` drives the
bidirectional loop with three concurrent concerns — inbound reader, outbound
drainer, abort watcher — first-wins cancellation.

Lifecycle responsibility (mirrors chat-completions' producer owning its httpx
client): the pump owns neither the WS open nor the WS close; the seam
(:mod:`otter_ai_realtime.connection`) opens the socket, calls :func:`pump`,
then closes the socket. The pump only drives an already-open socket.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

import websockets

from otter_ai_realtime._events import InboundTranslator, client_event_to_frame

if TYPE_CHECKING:
    from otter_ai_core.connection import ConnectionBackend
    from otter_ai_realtime.models import RealtimeModel


def realtime_url(model: RealtimeModel) -> str:
    """Build the Realtime WS URL from a model's ``base_url`` + ``id``.

    ``base_url`` is the provider's API base (e.g. ``https://api.openai.com/v1``);
    its scheme is mapped to ``wss`` (``ws`` for plain http) and
    ``/realtime?model={id}`` is appended. Generic by design — no provider
    detection.
    """
    parsed = urlparse(model.base_url)
    scheme = "wss" if parsed.scheme in ("https", "wss") else "ws"
    path = parsed.path.rstrip("/")
    netloc = parsed.netloc
    query = f"model={model.id}"
    return urlunparse((scheme, netloc, f"{path}/realtime", "", query, ""))


def _build_headers(model: RealtimeModel, api_key: str) -> list[tuple[str, str]]:
    """Build the WS handshake headers (list-of-tuples for ``websockets``)."""
    headers: list[tuple[str, str]] = [
        ("Authorization", f"Bearer {api_key}"),
        ("Content-Type", "application/json"),
    ]
    if model.headers:
        for key, value in model.headers.items():
            headers.append((key, value))
    return headers


async def connect_ws(model: RealtimeModel, api_key: str) -> Any:
    """Open the Realtime WebSocket.

    Raises on connect/handshake failure (the seam encodes this as a
    :class:`~otter_ai_core.model_connection.ConnectionErrorEvent`). Tests
    monkeypatch this to inject a fake socket.
    """
    url = realtime_url(model)
    headers = _build_headers(model, api_key)
    open_timeout = model.timeout_ms / 1000.0 if model.timeout_ms is not None else None
    return await websockets.connect(
        url,
        additional_headers=headers,
        open_timeout=open_timeout,
        max_size=None,
    )


async def pump(
    backend: ConnectionBackend[Any, Any],
    ws: Any,
    abort: asyncio.Event,
    translator: InboundTranslator,
) -> None:
    """Drive the bidirectional loop until one of three exits fires.

    * **outbound ends** — the caller closed the connection (graceful).
    * **abort set** — external cancel signal (graceful).
    * **inbound ends** — server closed the socket; clean close is graceful,
      an error propagates (the seam encodes it as a ``ConnectionErrorEvent``).

    First-wins: the first concern to complete cancels the others. Only a real
    inbound exception that initiates the stop (with abort unset) is re-raised.
    """
    inbound = asyncio.create_task(_read_inbound(ws, backend, translator))
    outbound = asyncio.create_task(_drain_outbound(ws, backend))
    aborter = asyncio.create_task(abort.wait())

    try:
        done, _pending = await asyncio.wait(
            {inbound, outbound, aborter}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for task in (inbound, outbound, aborter):
            if not task.done():
                task.cancel()

    # Capture whether inbound initiated the stop *before* awaiting cancellation.
    inbound_initiated = inbound in done
    inbound_exc: BaseException | None = None
    if inbound_initiated and not inbound.cancelled():
        inbound_exc = inbound.exception()

    # Await all tasks to surface / suppress cancellation noise.
    for task in (inbound, outbound, aborter):
        try:
            await task
        except BaseException:  # noqa: BLE001 — suppression is intentional.
            pass

    if (
        inbound_exc is not None
        and not abort.is_set()
        and not isinstance(inbound_exc, asyncio.CancelledError)
    ):
        raise inbound_exc


async def _read_inbound(
    ws: Any, backend: ConnectionBackend[Any, Any], translator: InboundTranslator
) -> None:
    """Read WS frames, translate, push server events onto the backend.

    Returns normally on a clean server close; raises :class:`ConnectionClosed`
    (or other) on a transport error.
    """
    async for raw in ws:
        try:
            frame = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(frame, dict):
            for event in translator.feed(frame):
                backend.push(event)


async def _drain_outbound(ws: Any, backend: ConnectionBackend[Any, Any]) -> None:
    """Drain caller client events, translate, send WS frames.

    Returns when the caller closes the outbound stream (``Connection.close()``).
    """
    async for client_event in backend:
        frame = client_event_to_frame(client_event)
        await ws.send(json.dumps(frame))


__all__ = ["connect_ws", "pump", "realtime_url"]
