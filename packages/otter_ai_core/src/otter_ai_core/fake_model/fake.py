import asyncio
from collections.abc import Iterable, Sequence
from enum import Enum, auto
from itertools import count
from types import TracebackType
from typing import Self

from otter_ai_core.types import (
    AssistantMessage,
    SessionMessage,
    TextContent,
    ToolResultMessage,
    UserMessage,
)


class FakeModelExhausted(RuntimeError): ...


class _SessionState(Enum):
    NEW = auto()
    OPEN = auto()
    CLOSED = auto()


class FakeModel:
    """A scripted chat model: `generate` returns the scripted assistant
    messages in order, and every message sent to the model is recorded and
    visible through `history`."""

    def __init__(
        self,
        responses: Iterable[AssistantMessage],
        generation_gate: asyncio.Event | None = None,
    ) -> None:
        self._responses = list(responses)
        self._generation_gate = generation_gate
        self._cursor = 0
        self._messages: list[SessionMessage] = []
        self._ids = count(1)
        self._state = _SessionState.NEW
        self._generating = False

    async def __aenter__(self) -> Self:
        """Opens the model's session. A model can only be entered once;
        re-entering raises RuntimeError."""
        if self._state is not _SessionState.NEW:
            raise RuntimeError(
                "FakeModel session can only be entered once; construct a new FakeModel"
            )
        self._state = _SessionState.OPEN
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Closes the session. Exceptions from the session body propagate."""
        self._state = _SessionState.CLOSED

    async def add_user_message(self, text: str) -> UserMessage:
        """Records and returns a user message carrying `text`. Raises
        RuntimeError outside an open session."""
        self._require_open("add_user_message")
        message = UserMessage(
            id=f"user-{next(self._ids)}",
            content=[TextContent(text=text)],
        )
        self._messages.append(message)
        return message

    async def add_tool_result_message(self, tool_call_id: str, text: str) -> ToolResultMessage:
        """Records and returns a tool result message for `tool_call_id`.
        Raises RuntimeError outside an open session."""
        self._require_open("add_tool_result_message")
        message = ToolResultMessage(
            id=f"tool-result-{next(self._ids)}",
            tool_call_id=tool_call_id,
            content=[TextContent(text=text)],
        )
        self._messages.append(message)
        return message

    async def generate(self) -> AssistantMessage:
        """Returns the next scripted assistant message and records it. Raises
        RuntimeError outside an open session or while another generate is in
        flight, and FakeModelExhausted when the script is exhausted. When a
        generation gate was supplied at construction, waits on it first."""
        self._require_open("generate")
        if self._generating:
            raise RuntimeError("generate() called while another generate() is in flight")
        self._generating = True
        try:
            if self._generation_gate is not None:
                await self._generation_gate.wait()
            if self._cursor >= len(self._responses):
                raise FakeModelExhausted(
                    f"script exhausted: generate() call {self._cursor + 1} "
                    f"but only {len(self._responses)} scripted response(s)"
                )
            message = self._responses[self._cursor]
            self._cursor += 1
            self._messages.append(message)
            return message
        finally:
            self._generating = False

    @property
    def history(self) -> Sequence[SessionMessage]:
        """Returns every message recorded this session, in order."""
        return tuple(self._messages)

    def _require_open(self, method: str) -> None:
        if self._state is not _SessionState.OPEN:
            raise RuntimeError(
                f"{method}() called outside an open session (state: {self._state.name})"
            )
