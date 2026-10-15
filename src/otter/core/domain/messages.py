"""The content passed between a caller and a model, independent of any provider's wire format."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    """An image carried inline: `data` is its bytes in base64, `media_type` its MIME type."""

    data: str
    media_type: str


@dataclass(frozen=True)
class ImageUrlPart:
    """An image the model's provider fetches for itself from `url`."""

    url: str


@dataclass(frozen=True)
class AudioPart:
    """A sound clip carried inline: `data` is its bytes in base64."""

    data: str
    format: Literal["wav", "mp3"]


@dataclass(frozen=True)
class ThinkingPart:
    """The reasoning a model showed on its way to a reply."""

    text: str


@dataclass(frozen=True)
class ToolCall:
    """A model's request to have a tool called; `id` is what the tool's result is matched by."""

    id: str
    name: str
    arguments: Mapping[str, object]


type UserPart = TextPart | ImagePart | ImageUrlPart | AudioPart
type AssistantPart = ThinkingPart | TextPart | ToolCall


@dataclass(frozen=True)
class AssistantMessage:
    """One turn produced by a model: its content parts, in the order the model produced them."""

    content: tuple[AssistantPart, ...]


@dataclass(frozen=True)
class ToolSpec:
    """What a model needs to know to ask for a tool: `parameters` is a JSON Schema object."""

    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class UserMessage:
    """One turn from the user: its content parts, in order."""

    content: tuple[UserPart, ...]


@dataclass(frozen=True)
class ToolResultMessage:
    """The result of a tool call a model asked for: `tool_call_id` is the call's `id`."""

    tool_call_id: str
    text: str


type ContextEntry = UserMessage | AssistantMessage | ToolResultMessage
"""One thing in the context a model is shown: a turn, or the result of a tool call."""
