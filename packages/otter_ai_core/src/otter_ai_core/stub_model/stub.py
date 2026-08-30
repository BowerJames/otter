import asyncio
from collections import deque
from enum import Enum, auto
from itertools import count
from types import TracebackType
from typing import Self

from otter_ai_core.types import (
    AssistantMessage,
    TextContent,
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
    deciding when the awaiting call is allowed to complete."""

    def __init__(self) -> None:
        self._state = _SessionState.NEW
        self._ids = count(1)
        self._user_seeds: deque[tuple[asyncio.Event, UserMessage]] = deque()

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

    def seed_user_message(self, text: str) -> tuple[asyncio.Event, UserMessage]:
        """Seeds the user message returned by the next `add_user_message`
        call. Returns the message together with an `asyncio.Event`; the
        awaiting `add_user_message` call completes only once the event is
        set."""
        event = asyncio.Event()
        message = UserMessage(
            id=f"user-{next(self._ids)}",
            content=[TextContent(text=text)],
        )
        self._user_seeds.append((event, message))
        return event, message

    async def add_user_message(self, text: str) -> UserMessage:
        """Returns the next seeded user message, completing only once its
        event has been set. Raises RuntimeError outside an open session and
        StubNotSeeded when no user message has been seeded."""
        self._require_open("add_user_message")
        event, message = self._take_user_seed()
        await event.wait()
        return message

    async def add_tool_result_message(self, tool_call_id: str, text: str) -> ToolResultMessage:
        """Raises StubNotSeeded: no tool result message has been seeded.
        Raises RuntimeError outside an open session."""
        self._require_open("add_tool_result_message")
        raise StubNotSeeded("add_tool_result_message() called but no tool result message seeded")

    async def generate(self) -> AssistantMessage:
        """Raises StubNotSeeded: no assistant message has been seeded. Raises
        RuntimeError outside an open session."""
        self._require_open("generate")
        raise StubNotSeeded("generate() called but no assistant message seeded")

    def _require_open(self, method: str) -> None:
        if self._state is not _SessionState.OPEN:
            raise RuntimeError(
                f"{method}() called outside an open session (state: {self._state.name})"
            )

    def _take_user_seed(self) -> tuple[asyncio.Event, UserMessage]:
        try:
            return self._user_seeds.popleft()
        except IndexError:
            raise StubNotSeeded("add_user_message() called but no user message seeded") from None
