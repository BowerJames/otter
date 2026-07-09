"""Reduced, app-facing event family for the agent bus.

The :data:`AgentEvent` family is what :class:`~otter_ai_agent.Agent` publishes
to its own :class:`~otter_ai_agent.AgentBus`. It is a **separate vocabulary
from** :data:`otter_ai_core.model_session.SessionEvent` (per the layering: the
session bus exposes reduced *response* events; the agent bus wraps those with
*turn* and *tool-execution* semantics). The agent subscribes to the session bus
internally and republishes/derives these events.

It is a port of pi's ``AgentEvent`` lifecycle, adapted to otter types:

* ``agent_start`` / ``agent_end`` — run lifecycle; ``agent_end`` carries the
  items added during the run.
* ``turn_start`` / ``turn_end`` — a turn is one assistant response plus any tool
  execution/results.
* ``message_start`` / ``message_update`` / ``message_end`` — item lifecycle.
  ``message_start`` / ``message_end`` carry a committed :class:`ContextItem`
  (with its server-assigned id); ``message_update`` carries the in-progress
  assistant :class:`AssistantMessage` snapshot plus the originating stream
  event, for live token rendering. For an assistant turn the ``message_start``
  item carries a synthetic empty ``id`` during streaming (the server-assigned id
  is not known until commit) and ``message_end`` carries the real id.
* ``tool_execution_start`` / ``tool_execution_update`` / ``tool_execution_end``
  — tool execution lifecycle; ``args`` / ``result`` / ``partial_result`` are
  typed ``Any`` (opaque payloads, mirroring pi) so a dataclass
  :class:`~otter_ai_agent.AgentToolResult` flows through unchanged.

Like the session family these are Pydantic v2 models with ``extra="forbid"``;
they remain serializable.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from otter_ai_core.assistant_message_stream import AssistantMessageEvent
from otter_ai_core.context import AssistantMessage, ContextItem, ToolResultMessage


class AgentEventType(StrEnum):
    """Discriminator values for :data:`AgentEvent` variants."""

    AgentStart = "agent.start"
    AgentEnd = "agent.end"
    TurnStart = "turn.start"
    TurnEnd = "turn.end"
    MessageStart = "message.start"
    MessageUpdate = "message.update"
    MessageEnd = "message.end"
    ToolExecutionStart = "tool_execution.start"
    ToolExecutionUpdate = "tool_execution.update"
    ToolExecutionEnd = "tool_execution.end"


# --------------------------------------------------------------------------- #
# Agent / turn lifecycle
# --------------------------------------------------------------------------- # #


class AgentStartEvent(BaseModel):
    """A run has begun (``stream`` / ``run`` / continuation started)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.AgentStart]


class AgentEndEvent(BaseModel):
    """A run has ended. ``items`` is the slice of :class:`ContextItem`\\ s added
    during this run (user prompt, assistant turns, tool results)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.AgentEnd]
    items: list[ContextItem]
    #: ``True`` when the run ended because the response errored or was aborted.
    error: bool = False


class TurnStartEvent(BaseModel):
    """One assistant response (+ any tool execution) is starting."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.TurnStart]


class TurnEndEvent(BaseModel):
    """A turn completed. ``message`` is the assistant message; ``tool_results``
    is empty when the model stopped without tool calls."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.TurnEnd]
    message: AssistantMessage
    tool_results: list[ToolResultMessage]


# --------------------------------------------------------------------------- #
# Message / item lifecycle
# --------------------------------------------------------------------------- #


class MessageStartEvent(BaseModel):
    """An item is entering the run.

    For user / tool-result items this carries the committed
    :class:`ContextItem` (with its id). For an assistant turn it carries the
    streaming :class:`AssistantMessage` wrapped as an
    :class:`~otter_ai_core.AssistantContextItem` with a synthetic empty ``id``
    (the server-assigned id arrives at commit; see :class:`MessageEndEvent`).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.MessageStart]
    item: ContextItem


class MessageUpdateEvent(BaseModel):
    """The in-progress assistant message has been updated (streaming delta).

    ``message`` is the full accumulated :class:`AssistantMessage` snapshot —
    replace, do not merge. ``stream_event`` is the originating assistant stream
    event for consumers that want per-block detail. Emitted only for assistant
    turns.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.MessageUpdate]
    message: AssistantMessage
    #: Originating assistant stream event, when available. The session's
    #: ``ResponseDeltaEvent`` collapses the nine per-block variants, so this is
    #: usually ``None``; consumers should render from ``message``.
    stream_event: AssistantMessageEvent | None = None


class MessageEndEvent(BaseModel):
    """An item has been committed to the conversation."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.MessageEnd]
    item: ContextItem


# --------------------------------------------------------------------------- #
# Tool execution lifecycle
# --------------------------------------------------------------------------- #


class ToolExecutionStartEvent(BaseModel):
    """A tool call is about to execute (after validation + ``before_tool_call``)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.ToolExecutionStart]
    tool_call_id: str
    tool_name: str
    args: Any


class ToolExecutionUpdateEvent(BaseModel):
    """A tool streamed a partial result."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.ToolExecutionUpdate]
    tool_call_id: str
    tool_name: str
    args: Any
    partial_result: Any


class ToolExecutionEndEvent(BaseModel):
    """A tool call finished. ``is_error`` is ``True`` for execution failures,
    blocked calls, validation failures, and truncation-failed calls."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[AgentEventType.ToolExecutionEnd]
    tool_call_id: str
    tool_name: str
    result: Any
    is_error: bool


AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | TurnStartEvent
    | TurnEndEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
)
"""Discriminated union of all events published on the agent bus."""
