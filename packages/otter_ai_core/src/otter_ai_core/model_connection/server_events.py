from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from otter_ai_core.context import (
    AssistantMessage,
    ContentType,
    ContextItem,
    Role,
    StopReason,
)


class ServerEventTypes(StrEnum):
    ContextItemAdded = "context_item.added"
    ResponseStarted = "response.started"
    ResponseTextContentStarted = "response.text_content.started"
    ResponseTextContentUpdated = "response.text_content.updated"
    ResponseTextContentDone = "response.text_content.done"
    ResponseThinkingContentStarted = "response.thinking_content.started"
    ResponseThinkingContentUpdated = "response.thinking_content.updated"
    ResponseThinkingContentDone = "response.thinking_content.done"
    ResponseToolCallStarted = "response.tool_call.started"
    ResponseToolCallUpdated = "response.tool_call.updated"
    ResponseToolCallDone = "response.tool_call.done"
    ResponseDone = "response.done"
    ResponseError = "response.error"
    ResponseAborted = "response.aborted"
    ConnectionError = "connection.error"


ResponseStopReasons = Literal[StopReason.Stop, StopReason.ToolUse, StopReason.Length]


class ContextItemAddedEvent(BaseModel):
    """A new context item has been added to the conversation context.

    ``item`` is the newly-added :class:`ContextItem` and ``item_id`` is
    the server-assigned identifier the client can use to reference or
    remove it later.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ContextItemAdded]
    item_id: str
    role: Role
    item: ContextItem


class ResponseStartedEvent(BaseModel):
    """The assistant has started generating a response.

    This is emitted once at the beginning of a response stream, before
    any content events. ``partial`` carries the initial
    :class:`AssistantMessage`, typically empty, that subsequent content
    events will populate.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseStarted]
    role: Literal[Role.Assistant]
    partial: AssistantMessage


class ResponseTextStartEvent(BaseModel):
    """The assistant has started generating a text content item.

    ``content_index`` identifies which entry within ``partial.content``
    this streamed text block occupies. ``partial`` carries the
    :class:`AssistantMessage` containing the newly-started text block;
    its text is typically empty here and is filled in by subsequent
    :class:`ResponseTextUpdatedEvent` deltas.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseTextContentStarted]
    role: Literal[Role.Assistant]
    content_type: Literal[ContentType.Text]
    content_index: int
    partial: AssistantMessage


class ResponseTextUpdatedEvent(BaseModel):
    """The assistant has updated an in-progress text content item.

    ``partial`` carries the accumulated :class:`AssistantMessage` whose
    ``content[content_index]`` is the text block reflecting the running
    concatenation of streamed text deltas so far.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseTextContentUpdated]
    role: Literal[Role.Assistant]
    content_type: Literal[ContentType.Text]
    content_index: int
    partial: AssistantMessage


class ResponseTextDoneEvent(BaseModel):
    """The assistant has finished generating a text content item.

    ``partial`` carries the :class:`AssistantMessage` whose
    ``content[content_index]`` is the completed text block with its
    final, fully-assembled text.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseTextContentDone]
    role: Literal[Role.Assistant]
    content_type: Literal[ContentType.Text]
    content_index: int
    partial: AssistantMessage


class ResponseThinkingStartEvent(BaseModel):
    """The assistant has started generating a thinking (reasoning) content item.

    ``content_index`` identifies which entry within ``partial.content``
    this streamed thinking block occupies. ``partial`` carries the
    :class:`AssistantMessage` containing the newly-started thinking
    block; its content is typically empty here and is filled in by
    subsequent :class:`ResponseThinkingUpdateEvent` deltas.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseThinkingContentStarted]
    role: Literal[Role.Assistant]
    content_type: Literal[ContentType.Thinking]
    content_index: int
    partial: AssistantMessage


class ResponseThinkingUpdateEvent(BaseModel):
    """The assistant has updated an in-progress thinking content item.

    ``partial`` carries the accumulated :class:`AssistantMessage` whose
    ``content[content_index]`` is the thinking block reflecting the
    running concatenation of streamed reasoning deltas so far.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseThinkingContentUpdated]
    role: Literal[Role.Assistant]
    content_type: Literal[ContentType.Thinking]
    content_index: int
    partial: AssistantMessage


class ResponseThinkingDoneEvent(BaseModel):
    """The assistant has finished generating a thinking content item.

    ``partial`` carries the :class:`AssistantMessage` whose
    ``content[content_index]`` is the completed thinking block with its
    final, fully-assembled reasoning content.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseThinkingContentDone]
    role: Literal[Role.Assistant]
    content_type: Literal[ContentType.Thinking]
    content_index: int
    partial: AssistantMessage


class ResponseToolCallStartEvent(BaseModel):
    """The assistant has started emitting a tool call.

    ``partial`` carries the in-progress :class:`AssistantMessage` whose
    ``content[content_index]`` is a :class:`ToolCall` block. The block's
    ``arguments`` are typically empty or partial at this point; the
    argument deltas arrive on subsequent
    :class:`ResponseToolCallUpdateEvent` events.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseToolCallStarted]
    role: Literal[Role.Assistant]
    content_type: Literal[ContentType.ToolCall]
    content_index: int
    partial: AssistantMessage


class ResponseToolCallUpdateEvent(BaseModel):
    """The assistant has updated an in-progress tool call.

    ``partial`` carries the accumulated :class:`AssistantMessage` whose
    ``content[content_index]`` is the :class:`ToolCall` block; its
    ``arguments`` reflect the running concatenation of streamed argument
    deltas.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseToolCallUpdated]
    role: Literal[Role.Assistant]
    content_type: Literal[ContentType.ToolCall]
    content_index: int
    partial: AssistantMessage


class ResponseToolCallDoneEvent(BaseModel):
    """The assistant has finished emitting a tool call.

    ``partial`` carries the :class:`AssistantMessage` whose
    ``content[content_index]`` is the completed :class:`ToolCall` block
    with its fully-assembled ``arguments``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseToolCallDone]
    role: Literal[Role.Assistant]
    content_type: Literal[ContentType.ToolCall]
    content_index: int
    partial: AssistantMessage


class ResponseDoneEvent(BaseModel):
    """The assistant has finished generating the response.

    This is emitted once at the end of a successful response stream,
    after all content events. ``partial`` carries the final, fully
    assembled :class:`AssistantMessage`.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseDone]
    role: Literal[Role.Assistant]
    reason: ResponseStopReasons
    partial: AssistantMessage


class ResponseErrorEvent(BaseModel):
    """An error occurred while generating the response.

    ``partial`` carries the most recently accumulated
    :class:`AssistantMessage` at the point the error occurred, which may
    be empty or partial.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseError]
    role: Literal[Role.Assistant]
    reason: Literal[StopReason.Error]
    partial: AssistantMessage


class ResponseAbortedEvent(BaseModel):
    """The response was aborted before completion.

    This is emitted when generation is cancelled (e.g. by client
    request) before finishing. ``partial`` carries the most recently accumulated
    :class:`AssistantMessage` at the point of abort.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ResponseAborted]
    role: Literal[Role.Assistant]
    reason: Literal[StopReason.Aborted]
    partial: AssistantMessage


class ConnectionErrorEvent(BaseModel):
    """A connection-level failure outside any single response.

    Unlike :class:`ResponseErrorEvent` / :class:`ResponseAbortedEvent` (which
    describe the outcome of one response), this fires when the underlying
    transport itself fails — e.g. a WebSocket connect/handshake failure or a
    mid-session transport error. It carries no ``partial`` assistant message
    because the failure occurs outside a response.

    After emitting this the backend calls ``end()``; the caller's inbound
    iteration stops. A graceful teardown (caller ``close()`` or the external
    ``abort`` signal) does **not** emit this event — only failures do.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerEventTypes.ConnectionError]
    #: Human-readable failure description.
    message: str
    #: Coarse failure category, e.g. ``"connect_failed"`` /
    #: ``"handshake_failed"`` / ``"transport_error"``.
    reason: str


ServerEvent = (
    ContextItemAddedEvent
    | ResponseStartedEvent
    | ResponseTextStartEvent
    | ResponseTextUpdatedEvent
    | ResponseTextDoneEvent
    | ResponseThinkingStartEvent
    | ResponseThinkingUpdateEvent
    | ResponseThinkingDoneEvent
    | ResponseToolCallStartEvent
    | ResponseToolCallUpdateEvent
    | ResponseToolCallDoneEvent
    | ResponseDoneEvent
    | ResponseErrorEvent
    | ResponseAbortedEvent
    | ConnectionErrorEvent
)
"""Discriminated union of all server-to-client response stream events."""
