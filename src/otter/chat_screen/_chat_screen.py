"""What a chat needs of the screen it is shown on, whatever draws it."""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Protocol, Self


@dataclass(frozen=True)
class UserLine:
    """Something the user said."""

    text: str


@dataclass(frozen=True)
class ThinkingLine:
    """Reasoning the model showed on its way to a reply."""

    text: str


@dataclass(frozen=True)
class AssistantLine:
    """Something the model said."""

    text: str


@dataclass(frozen=True)
class ToolCallLine:
    """The model asked to have the tool `name` called with `arguments`."""

    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class ToolResultLine:
    """What a tool the model asked for came back with."""

    text: str


@dataclass(frozen=True)
class ErrorLine:
    """Something went wrong."""

    text: str


@dataclass(frozen=True)
class NoticeLine:
    """A word to the user from the chat itself, not part of the conversation."""

    text: str


type TranscriptLine = (
    UserLine | ThinkingLine | AssistantLine | ToolCallLine | ToolResultLine | ErrorLine | NoticeLine
)
"""One thing in the transcript of a chat: what it is, not how it looks."""

type Status = Literal["working", "idle", "stopped"]
"""What the chat is doing: answering, at rest, or halted by an error."""


class ChatScreen(Protocol):
    """A screen a chat is shown on: a transcript, a status, and a place to type.

    A screen is an async context manager: entering puts it up and leaving takes it
    down, so use it in `async with`, and only while it is up. Once the user has quit,
    what is shown is dropped.
    """

    def show(self, line: TranscriptLine) -> None:
        """Add `line` to the end of the transcript."""
        ...

    def set_status(self, status: Status) -> None:
        """Show what the chat is doing, in place of the status shown before."""
        ...

    def submissions(self) -> AsyncIterator[str]:
        """Each message the user submits, as it is submitted.

        Finishes once the user quits.
        """
        ...

    async def __aenter__(self) -> Self:
        """Put the screen up; it is returned."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Take the screen down."""
        ...
