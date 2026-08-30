import asyncio
from collections import deque
from enum import Enum, auto
from types import TracebackType
from typing import Self

from otter_ai_core.types import (
    AssistantMessage,
    ToolResultMessage,
    UserMessage,
)


class StubNotSeeded(RuntimeError): ...


class _SessionState(Enum):
    NEW = auto()
    OPEN = auto()
    CLOSED = auto()


class StubModel:
    """A scriptable chat model for tests: every message the model returns
    must be seeded by the test before the model is asked for it. Each seed
    pairs the message with an `asyncio.Event` that the test controls,
    deciding when the awaiting call is allowed to complete. Messages are
    returned exactly as seeded and never inspected."""

    def __init__(self) -> None:
        self._state = _SessionState.NEW
        self._user_seeds: deque[tuple[asyncio.Event, UserMessage]] = deque()
        self._tool_result_seeds: deque[tuple[asyncio.Event, ToolResultMessage]] = deque()
        self._assistant_seeds: deque[tuple[asyncio.Event, AssistantMessage]] = deque()

    async def __aenter__(self) -> Self:
        """Opens the model's session. A model can only be entered once;
        re-entering raises RuntimeError."""
        if self._state is not _SessionState.NEW:
            raise RuntimeError(
                "StubModel session can only be entered once; construct a new StubModel"
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

    def seed_user_message(self, message: UserMessage) -> asyncio.Event:
        """Seeds the message returned by the next `add_user_message` call.
        Returns the `asyncio.Event` that the awaiting call completes on."""
        event = asyncio.Event()
        self._user_seeds.append((event, message))
        return event

    def seed_tool_result_message(self, message: ToolResultMessage) -> asyncio.Event:
        """Seeds the message returned by the next `add_tool_result_message`
        call. Returns the `asyncio.Event` that the awaiting call completes
        on."""
        event = asyncio.Event()
        self._tool_result_seeds.append((event, message))
        return event

    def seed_generate(self, message: AssistantMessage) -> asyncio.Event:
        """Seeds the message returned by the next `generate` call. Returns
        the `asyncio.Event` that the awaiting call completes on."""
        event = asyncio.Event()
        self._assistant_seeds.append((event, message))
        return event

    async def add_user_message(self, text: str) -> UserMessage:
        """Returns the next seeded user message, completing only once its
        event has been set. Raises RuntimeError outside an open session and
        StubNotSeeded when no user message has been seeded."""
        self._require_open("add_user_message")
        event, message = self._take_seed(self._user_seeds, "add_user_message()", "user message")
        await event.wait()
        return message

    async def add_tool_result_message(self, tool_call_id: str, text: str) -> ToolResultMessage:
        """Returns the next seeded tool result message, completing only once
        its event has been set. `tool_call_id` and `text` are not inspected.
        Raises RuntimeError outside an open session and StubNotSeeded when no
        tool result message has been seeded."""
        self._require_open("add_tool_result_message")
        event, message = self._take_seed(
            self._tool_result_seeds, "add_tool_result_message()", "tool result message"
        )
        await event.wait()
        return message

    async def generate(self) -> AssistantMessage:
        """Returns the next seeded assistant message, completing only once
        its event has been set. Raises RuntimeError outside an open session
        and StubNotSeeded when no assistant message has been seeded."""
        self._require_open("generate")
        event, message = self._take_seed(self._assistant_seeds, "generate()", "assistant message")
        await event.wait()
        return message

    def _require_open(self, method: str) -> None:
        if self._state is not _SessionState.OPEN:
            raise RuntimeError(
                f"{method} called outside an open session (state: {self._state.name})"
            )

    def _take_seed[M](
        self, seeds: deque[tuple[asyncio.Event, M]], method: str, seeded: str
    ) -> tuple[asyncio.Event, M]:
        try:
            return seeds.popleft()
        except IndexError:
            raise StubNotSeeded(f"{method} called but no {seeded} seeded") from None
