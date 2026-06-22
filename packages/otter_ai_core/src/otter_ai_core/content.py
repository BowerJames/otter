"""Content blocks that make up message ``content`` lists.

There are two discriminated unions:

* :data:`UserContent` — blocks allowed in user messages and tool results
  (``text`` / ``image``).
* :data:`AssistantContent` — blocks allowed in assistant messages
  (``text`` / ``thinking`` / ``tool_call``).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TextContent(BaseModel):
    """A plain text block."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: str
    #: Opaque provider-specific text signature (e.g. an OpenAI responses text
    #: item id). Inert in otter; preserved for replay elsewhere.
    text_signature: str | None = None


class ImageContent(BaseModel):
    """An image block, carried as base64-encoded bytes."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["image"]
    #: Base64-encoded image data.
    data: str
    #: MIME type, e.g. ``"image/jpeg"``, ``"image/png"``.
    mime_type: str


class ThinkingContent(BaseModel):
    """A reasoning/thinking block emitted by the model."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["thinking"]
    thinking: str
    #: Opaque provider signature required to replay reasoning across turns.
    #: Inert in otter; preserved for replay elsewhere.
    thinking_signature: str | None = None
    #: When ``True`` the thinking content was redacted by safety filters; the
    #: opaque encrypted payload is carried in :attr:`thinking_signature`.
    redacted: bool | None = None


class ToolCall(BaseModel):
    """A request from the model to invoke a tool."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_call"]
    id: str
    name: str
    #: Parsed tool arguments. Values are arbitrary JSON-compatible structures.
    arguments: dict[str, Any]
    #: Provider-specific opaque signature for reusing thought context (Google).
    #: Inert in otter; preserved for replay elsewhere.
    thought_signature: str | None = None


#: Blocks allowed in user messages and tool results.
UserContent = Annotated[TextContent | ImageContent, Field(discriminator="type")]

#: Blocks allowed in assistant messages.
AssistantContent = Annotated[
    TextContent | ThinkingContent | ToolCall, Field(discriminator="type")
]
