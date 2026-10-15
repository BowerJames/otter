"""Test adapters for the connections the realtime adapter opens."""

import base64
import io
import wave
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from openai.types.realtime import RealtimeClientEventParam, RealtimeServerEvent
from pydantic import TypeAdapter

_SERVER_EVENT: TypeAdapter[RealtimeServerEvent] = TypeAdapter(RealtimeServerEvent)


def text_item(text: str) -> dict[str, Any]:
    """The wire form of an output item in which the model writes `text`."""
    return {
        "id": "item_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text}],
    }


def tool_call_item(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    """The wire form of an output item asking for one tool call; `arguments` is JSON text."""
    return {
        "id": f"item_{call_id}",
        "type": "function_call",
        "status": "completed",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }


def text_delta(text: str) -> dict[str, Any]:
    """The wire form of the event carrying the next piece of text the model writes."""
    return {
        "type": "response.output_text.delta",
        "event_id": "event_1",
        "response_id": "resp_1",
        "item_id": "item_1",
        "output_index": 0,
        "content_index": 0,
        "delta": text,
    }


def done(*output: dict[str, Any], status: str = "completed", **more: Any) -> dict[str, Any]:
    """The wire form of the event that ends a turn whose output items are `output`."""
    return {
        "type": "response.done",
        "event_id": "event_1",
        "response": {
            "id": "resp_1",
            "object": "realtime.response",
            "status": status,
            "output": list(output),
            **more,
        },
    }


def error(message: str) -> dict[str, Any]:
    """The wire form of the event in which the endpoint reports that something failed."""
    return {
        "type": "error",
        "event_id": "event_1",
        "error": {"type": "invalid_request_error", "message": message},
    }


FAILED = done(
    status="failed",
    status_details={"type": "failed", "error": {"type": "server_error", "code": "overloaded"}},
)
LOST = {"type": "connection.lost"}


def wav(pcm: bytes, *, rate: int = 24000, channels: int = 1) -> str:
    """The base64 of a 16-bit wav file whose samples are `pcm`."""
    file = io.BytesIO()
    with wave.open(file, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm)
    return base64.b64encode(file.getvalue()).decode()


class FakeConnection:
    """One connection to the fake endpoint: `sent` is every event sent over it, in order."""

    def __init__(self, endpoint: "FakeRealtimeEndpoint") -> None:
        self.sent: list[Any] = []
        self.closed = False
        self._endpoint = endpoint
        self._arriving: deque[dict[str, Any]] = deque()

    async def send(self, event: RealtimeClientEventParam) -> None:
        self.sent.append(event)
        if event["type"] == "response.create":
            self._arriving.extend(self._endpoint.next_turn())

    async def __aiter__(self) -> AsyncIterator[RealtimeServerEvent]:
        while self._arriving:
            event = self._arriving.popleft()
            if event["type"] == "connection.lost":
                raise ConnectionError("connection lost")
            yield _SERVER_EVENT.validate_python(event)

    def items(self) -> list[Any]:
        """The conversation items sent over this connection, in order."""
        return [e["item"] for e in self.sent if e["type"] == "conversation.item.create"]

    def sessions(self) -> list[Any]:
        """The sessions the endpoint was told over this connection, in order."""
        return [e["session"] for e in self.sent if e["type"] == "session.update"]


class FakeRealtimeEndpoint:
    """Records each connection made to it, and answers with scripted turns.

    Each request for a response is answered with the next entry of `turns`, the server
    events of one turn; once they run out, with a plain text turn. A turn that ends
    without a `response.done` leaves the connection closed by the endpoint, and one
    holding `LOST` breaks the connection at that point. While `fail_to_connect` is set,
    connecting raises it.
    """

    def __init__(self) -> None:
        self.models: list[str] = []
        self.connections: list[FakeConnection] = []
        self.turns: list[list[dict[str, Any]]] = []
        self.fail_to_connect: Exception | None = None

    @asynccontextmanager
    async def __call__(self, model: str) -> AsyncIterator[FakeConnection]:
        if self.fail_to_connect is not None:
            raise self.fail_to_connect
        self.models.append(model)
        connection = FakeConnection(self)
        self.connections.append(connection)
        try:
            yield connection
        finally:
            connection.closed = True

    def next_turn(self) -> list[dict[str, Any]]:
        return self.turns.pop(0) if self.turns else [done(text_item("OK"))]
