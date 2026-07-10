"""Shared helpers for otter_ai_agent tests.

Tests drive a :class:`ModelSession` against a bare
:func:`~otter_ai_core.create_bidirectional_channel` pair whose backend a scripted
``run_backend`` task drives -- mirroring ``test_model_session.py``. The script
responds to the agent's ``ResponseCreate`` with canned server events, echoes
``ContextItemAddEvent``\\ s as ``ContextItemAdded``, and turns
``AbortResponseEvent`` into ``ResponseAborted``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from otter_ai_core import (
    AssistantMessage,
    BidirectionalChannel,
    BidirectionalChannelBackend,
    BidirectionalChannelWiring,
    StopReason,
    Usage,
    UsageCost,
    create_bidirectional_channel,
)
from otter_ai_core.context import (
    AssistantContextItem,
    ContentType,
    Role,
    TextContent,
    ToolCall,
)
from otter_ai_core.model_connection.client_events import (
    AbortResponseEvent,
    ClientEvent,
    ContextItemAddEvent,
    ResponseCreate,
)
from otter_ai_core.model_connection.server_events import (
    ContextItemAddedEvent,
    ResponseAbortedEvent,
    ResponseDoneEvent,
    ResponseErrorEvent,
    ResponseStartedEvent,
    ResponseTextUpdatedEvent,
    ServerEvent,
    ServerEventTypes,
)


def zero_usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost=UsageCost(
            input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0
        ),
    )


def assistant(
    content: list[Any],
    stop_reason: StopReason = StopReason.Stop,
    error_message: str | None = None,
) -> AssistantMessage:
    return AssistantMessage(
        role=Role.Assistant,
        content=list(content),
        api="test",
        provider="test",
        model="test-model",
        usage=zero_usage(),
        stop_reason=stop_reason,
        error_message=error_message,
        timestamp=0,
    )


def text_block(s: str) -> TextContent:
    return TextContent(type=ContentType.Text, text=s)


def tool_call(call_id: str, name: str, args: dict[str, Any]) -> ToolCall:
    return ToolCall(type=ContentType.ToolCall, id=call_id, name=name, arguments=args)


# --------------------------------------------------------------------------- #
# Backend scripting
# --------------------------------------------------------------------------- #


@dataclass
class TurnScript:
    """One canned model response.

    ``kind`` selects the terminal: ``"done"`` (requires ``stop_reason`` in
    {stop, tool_use, length}), ``"error"``, or ``"aborted"``.
    """

    content: list[Any] = field(default_factory=list)
    stop_reason: StopReason = StopReason.Stop
    kind: str = "done"
    error_message: str | None = None
    #: Emit a streaming text delta before the terminal (exercises MessageUpdate).
    stream_text: bool = False


def new_session() -> tuple[
    BidirectionalChannel[ClientEvent, ServerEvent],
    BidirectionalChannelBackend[ClientEvent, ServerEvent],
]:
    wiring: BidirectionalChannelWiring[ClientEvent, ServerEvent]
    wiring = create_bidirectional_channel()
    return wiring.caller, wiring.backend


async def _emit_turn(
    backend: BidirectionalChannelBackend[ClientEvent, ServerEvent], script: TurnScript
) -> None:
    msg = assistant(script.content, script.stop_reason, script.error_message)
    empty = assistant([], script.stop_reason)
    backend.push(
        ResponseStartedEvent(
            type=ServerEventTypes.ResponseStarted, role=Role.Assistant, partial=empty
        )
    )
    if script.stream_text:
        backend.push(
            ResponseTextUpdatedEvent(
                type=ServerEventTypes.ResponseTextContentUpdated,
                role=Role.Assistant,
                content_type=ContentType.Text,
                content_index=0,
                partial=msg,
            )
        )
    if script.kind == "done":
        backend.push(
            ResponseDoneEvent(
                type=ServerEventTypes.ResponseDone,
                role=Role.Assistant,
                reason=script.stop_reason,
                partial=msg,
            )
        )
        item = AssistantContextItem.from_message(msg, str(uuid.uuid4()))
        backend.push(
            ContextItemAddedEvent(
                type=ServerEventTypes.ContextItemAdded,
                item_id=item.id,
                role=Role.Assistant,
                item=item,
            )
        )
    elif script.kind == "error":
        backend.push(
            ResponseErrorEvent(
                type=ServerEventTypes.ResponseError,
                role=Role.Assistant,
                reason=StopReason.Error,
                partial=msg,
            )
        )
    elif script.kind == "aborted":
        backend.push(
            ResponseAbortedEvent(
                type=ServerEventTypes.ResponseAborted,
                role=Role.Assistant,
                reason=StopReason.Aborted,
                partial=msg,
            )
        )
    await asyncio.sleep(0)


async def run_backend(
    backend: BidirectionalChannelBackend[ClientEvent, ServerEvent],
    scripts: Sequence[TurnScript],
    received: list[ClientEvent],
) -> None:
    """Drive ``backend`` against a fixed script of model responses.

    Responds to each ``ResponseCreate`` with the next script; echoes caller
    item-adds; turns aborts into ``ResponseAborted``. Exits when the scripts
    are exhausted or the caller closes the connection.
    """
    it = iter(scripts)
    try:
        async for client_event in backend:
            received.append(client_event)
            if isinstance(client_event, ResponseCreate):
                try:
                    await _emit_turn(backend, next(it))
                except StopIteration:
                    break
            elif isinstance(client_event, ContextItemAddEvent):
                item = client_event.item
                backend.push(
                    ContextItemAddedEvent(
                        type=ServerEventTypes.ContextItemAdded,
                        item_id=item.id,
                        role=item.role,
                        item=item,
                    )
                )
            elif isinstance(client_event, AbortResponseEvent):
                backend.push(
                    ResponseAbortedEvent(
                        type=ServerEventTypes.ResponseAborted,
                        role=Role.Assistant,
                        reason=StopReason.Aborted,
                        partial=assistant([], StopReason.Aborted),
                    )
                )
    finally:
        backend.end()


async def collect_stream(it: AsyncIterator[Any]) -> list[Any]:
    out: list[Any] = []
    async for event in it:
        out.append(event)
    return out
