"""Shared test helpers for the assistant-provider-stream tests.

Includes catalog-model factories (for unit tests), a thin copy of the httpx
transport-faking helpers from ``otter_ai_chat_completions`` (for the chat
end-to-end test), a minimal fake realtime WebSocket (copied because the
realtime package's ``tests`` module is not shipped with the wheel), and
connection-driving helpers for the new
:func:`create_model_connection_by_provider` seam.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import pytest

from otter_ai_assistant_provider_stream import create_model_connection_by_provider
from otter_ai_chat_completions import (
    ChatCompletionsCost,
    ChatCompletionsModel,
)
from otter_ai_chat_completions import stream as stream_module
from otter_ai_core import Context, UserMessage, context_item
from otter_ai_core.model_connection import (
    ModelConnection,
    ResponseDoneEvent,
    ResponseErrorEvent,
)


def model_kwargs(**overrides: Any) -> dict[str, Any]:
    """Minimal valid ``ChatCompletionsModel`` kwargs (provider/model overrideable).

    Returns a dict of sensible defaults so tests can build a catalog model
    with ``ChatCompletionsModel(**model_kwargs(reasoning=False, ...))``. The
    ``provider``/``id`` defaults are non-built-in so a test model never
    collides with a real catalog entry.
    """
    base: dict[str, Any] = {
        "id": "test-model",
        "name": "Test Model",
        "provider": "test-provider",
        "base_url": "https://example.test/v1",
        "api": "chat-completions",
        "reasoning": True,
        "input_modalities": ["text"],
        "context_window": 8192,
        "max_tokens": 4096,
        "cost": ChatCompletionsCost(
            input=1.0, output=2.0, cache_read=0.5, cache_write=0.0
        ),
    }
    base.update(overrides)
    return base


def simple_context(text: str = "hello") -> Context:
    return Context(
        system_prompt=None,
        items=[
            context_item(
                message=UserMessage(role="user", content=text, timestamp=0), id="u1"
            )
        ],
    )


def start_connection(
    options: Any,
    context: Context,
    abort: asyncio.Event | None = None,
) -> ModelConnection:
    """Two-step convenience: build the provider-dispatch connection fn, then call it.

    The seam is a builder — ``create_model_connection_by_provider`` takes
    ``options`` and returns a ``ModelConnectionFn``, which is then called with
    ``(context, abort)``. ``abort`` defaults to a fresh, unset
    :class:`asyncio.Event`.
    """
    if abort is None:
        abort = asyncio.Event()
    return create_model_connection_by_provider(options)(context, abort)


async def drive_connection(
    conn: ModelConnection,
    client_events: Sequence[Any],
) -> list[Any]:
    """Send ``client_events`` then drain the connection to completion.

    For a request-driven (chat) connection the caller passes a
    :class:`~otter_ai_core.model_connection.ResponseCreate`; the connection is
    closed once a terminal response event is observed so the idle loop stops
    cleanly. For a realtime connection the caller may pass nothing and rely on
    the server closing (the fake WS's ``close_inbound``), or pass client events
    likewise.
    """
    for event in client_events:
        conn.send(event)
    out: list[Any] = []
    async for event in conn:
        out.append(event)
        if isinstance(event, (ResponseDoneEvent, ResponseErrorEvent)):
            # Chat path: the turn ended — close so the idle loop stops.
            conn.close()
    return out


def sse_response(
    chunks: Sequence[dict[str, Any]] | None, status: int = 200
) -> httpx.Response:
    """Build a streaming SSE response carrying ``chunks`` as JSON ``data:`` lines."""
    body_lines: list[str] = []
    if chunks is not None:
        for chunk in chunks:
            body_lines.append("data: " + json.dumps(chunk))
        body_lines.append("data: [DONE]")
    content = ("\n\n".join(body_lines) + "\n\n").encode("utf-8") if body_lines else b""
    return httpx.Response(
        status_code=status,
        headers={"content-type": "text/event-stream"},
        content=content,
    )


def install_fake_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    """Monkeypatch the chat-completions ``_create_client`` to use a ``MockTransport``.

    Mirrors the faking seam from issue #13 decision #10. The transport is
    shared across sends so streaming + retries both flow through ``handler``.
    """
    transport = httpx.MockTransport(handler)

    def fake_create_client(
        model: ChatCompletionsModel,
        api_key: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> httpx.AsyncClient:
        del timeout_seconds
        return httpx.AsyncClient(
            base_url=model.base_url,
            headers={**headers, "Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    monkeypatch.setattr(stream_module, "_create_client", fake_create_client)


async def collect(stream: Any) -> list[Any]:
    return [event async for event in stream]


# --------------------------------------------------------------------------- #
# Fake realtime WebSocket (copied from otter_ai_realtime/tests/_realtime_helpers)
# --------------------------------------------------------------------------- #


class FakeRealtimeWS:
    """A minimal async fake of a ``websockets`` connection."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._inbound: asyncio.Queue[Any] = asyncio.Queue()
        self.closed: bool = False

    def feed(self, *frames: dict[str, Any]) -> None:
        for frame in frames:
            self._inbound.put_nowait(json.dumps(frame))

    def close_inbound(self) -> None:
        self._inbound.put_nowait(None)

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            item = await self._inbound.get()
            if item is None:
                return
            yield item

    async def send(self, raw: str) -> None:
        if self.closed:
            raise RuntimeError("send on closed socket")
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True


def install_fake_realtime(
    monkeypatch: pytest.MonkeyPatch, fake: FakeRealtimeWS
) -> None:
    """Monkeypatch ``connect_ws`` to return ``fake``."""
    import otter_ai_realtime._transport as transport

    async def _connect(model: Any, api_key: str) -> FakeRealtimeWS:  # noqa: ARG001
        return fake

    monkeypatch.setattr(transport, "connect_ws", _connect)


__all__ = [
    "FakeRealtimeWS",
    "collect",
    "drive_connection",
    "install_fake_realtime",
    "install_fake_transport",
    "model_kwargs",
    "simple_context",
    "sse_response",
    "start_connection",
]
