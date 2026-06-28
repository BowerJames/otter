"""Shared test helpers: a fake realtime WebSocket + builders.

Mirrors the chat-completions ``_helpers.py`` pattern (fake the transport, not
the network): :class:`FakeRealtimeWS` records outbound frames and yields
inbound frames from a test-supplied queue. The connection tests monkeypatch
:func:`otter_ai_realtime._transport.connect_ws` to return one.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from otter_ai_core import (
    AssistantMessage,
    Context,
    TextContent,
    Tool,
    Usage,
    UsageCost,
    UserMessage,
    context_item,
)
from otter_ai_realtime.models import RealtimeCost, RealtimeModel
from otter_ai_realtime.options import RealtimeModelOptions


def make_model(**overrides: Any) -> RealtimeModel:
    defaults: dict[str, Any] = dict(
        id="gpt-4o-realtime-preview",
        name="GPT-4o Realtime",
        provider="openai",
        base_url="https://api.openai.com/v1",
        input_modalities=["text"],
        context_window=128000,
        max_tokens=4096,
        cost=RealtimeCost(input=5.0, output=20.0, cache_read=2.5, cache_write=0.0),
        api_key="test-key",
    )
    defaults.update(overrides)
    return RealtimeModel(**defaults)


def make_options(**overrides: Any) -> RealtimeModelOptions:
    opts: dict[str, Any] = dict(model=make_model())
    opts.update(overrides)
    return RealtimeModelOptions(**opts)


def simple_context(*messages: Any, system_prompt: str | None = None) -> Context:
    items: list[Any] = []
    for i, msg in enumerate(messages):
        items.append(context_item(message=msg, id=f"seed-{i}"))
    return Context(system_prompt=system_prompt, items=items, tools=[])


def user_text(text: str, timestamp: int = 0) -> UserMessage:
    return UserMessage(role="user", content=text, timestamp=timestamp)


def text_frame_delta(delta: str) -> dict[str, Any]:
    return {"type": "response.text.delta", "delta": delta}


def text_frame_done(text: str) -> dict[str, Any]:
    return {"type": "response.text.done", "text": text}


def content_part_added() -> dict[str, Any]:
    return {
        "type": "response.content_part.added",
        "part": {"type": "text", "text": ""},
    }


def fc_item_added(call_id: str, name: str) -> dict[str, Any]:
    return {
        "type": "response.output_item.added",
        "item": {"type": "function_call", "call_id": call_id, "name": name},
    }


def fc_args_delta(delta: str) -> dict[str, Any]:
    return {"type": "response.function_call_arguments.delta", "delta": delta}


def fc_args_done(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    return {
        "type": "response.function_call_arguments.done",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }


def response_created(resp_id: str = "resp_1") -> dict[str, Any]:
    return {"type": "response.created", "response": {"id": resp_id}}


def response_completed() -> dict[str, Any]:
    return {"type": "response.completed", "response": {"status": "completed"}}


def response_cancelled() -> dict[str, Any]:
    return {"type": "response.cancelled", "response": {"status": "cancelled"}}


def error_frame(message: str = "boom") -> dict[str, Any]:
    return {"type": "error", "error": {"message": message}}


class FakeRealtimeWS:
    """A minimal async fake of a ``websockets`` connection.

    Push inbound frames via :meth:`recv` (they are awaited by the pump's
    inbound reader). Inspect sent frames via :attr:`sent`. ``raise_on_recv``
    simulates a transport error mid-stream.
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._inbound: asyncio.Queue[Any] = asyncio.Queue()
        self.raise_on_recv: BaseException | None = None
        self.closed: bool = False

    # -- inbound (server → client) -------------------------------------- #

    def feed(self, *frames: dict[str, Any]) -> None:
        for frame in frames:
            self._inbound.put_nowait(json.dumps(frame))

    def close_inbound(self) -> None:
        """Signal that the server has closed the stream (clean EOF)."""
        self._inbound.put_nowait(None)

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            if self.raise_on_recv is not None:
                raise self.raise_on_recv
            item = await self._inbound.get()
            if item is None:
                return
            yield item

    # -- outbound (client → server) ------------------------------------- #

    async def send(self, raw: str) -> None:
        if self.closed:
            raise RuntimeError("send on closed socket")
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True


def collect(translator_or_translator: Any, frames: list[dict[str, Any]]) -> list[Any]:
    """Feed ``frames`` through an :class:`InboundTranslator`, collecting events."""
    out: list[Any] = []
    for frame in frames:
        out.extend(translator_or_translator.feed(frame))
    return out


# Re-export some core bits tests use so they can star-import helpers.
__all__ = [
    "Context",
    "FakeRealtimeWS",
    "Tool",
    "UserMessage",
    "TextContent",
    "AssistantMessage",
    "Usage",
    "UsageCost",
    "collect",
    "content_part_added",
    "context_item",
    "error_frame",
    "fc_args_delta",
    "fc_args_done",
    "fc_item_added",
    "make_model",
    "make_options",
    "response_cancelled",
    "response_completed",
    "response_created",
    "simple_context",
    "text_frame_delta",
    "text_frame_done",
    "user_text",
]
