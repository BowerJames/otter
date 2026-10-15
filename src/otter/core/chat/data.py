"""What a chat shows, and what it is told of the session it holds."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from otter.core.domain.messages import ContextEntry


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


@dataclass(frozen=True)
class Idle:
    """The session has come to rest: it is waiting for the user."""


type SessionUpdate = ContextEntry | Idle
"""Something that happened in the session: an entry joined its conversation, or it came to rest."""
