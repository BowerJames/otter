from __future__ import annotations

from enum import StrEnum
from typing import Any

from otter_ai_core.bus import BusEvent
from otter_ai_core.model_connection import (
    BranchMoved,
    CompactionDone,
    ResponseDone,
    ResponseStarted,
    ResponseUpdated,
    ServerContextEventType,
    ToolResultAdded,
    UserItemAdded,
    UserItemUpdated,
)


class ModelControllerEventTypes(StrEnum):
    RESPONSE_STARTED = ServerContextEventType.RESPONSE_STARTED
    RESPONSE_UPDATED = ServerContextEventType.RESPONSE_UPDATED
    RESPONSE_DONE = ServerContextEventType.RESPONSE_DONE
    USER_ITEM_ADDED = ServerContextEventType.USER_ITEM_ADDED
    USER_ITEM_UPDATED = ServerContextEventType.USER_ITEM_UPDATED
    TOOL_RESULT_ADDED = ServerContextEventType.TOOL_RESULT_ADDED
    COMPACTION_DONE = ServerContextEventType.COMPACTION_DONE
    BRANCH_MOVED = ServerContextEventType.BRANCH_MOVED


#: Emitted when a response generation starts (``partial`` is the empty-start item).
RESPONSE_STARTED: BusEvent[ResponseStarted] = BusEvent(ModelControllerEventTypes.RESPONSE_STARTED)
#: Emitted for each in-progress assistant-item snapshot.
RESPONSE_UPDATED: BusEvent[ResponseUpdated] = BusEvent(ModelControllerEventTypes.RESPONSE_UPDATED)
#: Emitted when a response generation completes (carries the final assistant item).
RESPONSE_DONE: BusEvent[ResponseDone] = BusEvent(ModelControllerEventTypes.RESPONSE_DONE)
#: Emitted when the server accepts a user message and assigns it an item ``id``.
USER_ITEM_ADDED: BusEvent[UserItemAdded] = BusEvent(ModelControllerEventTypes.USER_ITEM_ADDED)
#: Emitted when a previously-added user item is amended server-side.
USER_ITEM_UPDATED: BusEvent[UserItemUpdated] = BusEvent(ModelControllerEventTypes.USER_ITEM_UPDATED)
#: Emitted when the server accepts a tool result and assigns it an item ``id``.
TOOL_RESULT_ADDED: BusEvent[ToolResultAdded] = BusEvent(ModelControllerEventTypes.TOOL_RESULT_ADDED)
#: Emitted when a stateful server confirms a ``compaction.create`` (the live
#: history was collapsed in place; carries ``error_message`` if refused/failed).
COMPACTION_DONE: BusEvent[CompactionDone] = BusEvent(ModelControllerEventTypes.COMPACTION_DONE)
#: Emitted when a stateful server confirms a ``branch.move`` (the live
#: conversation was truncated to ``at_item_id``; carries ``error_message``).
BRANCH_MOVED: BusEvent[BranchMoved] = BusEvent(ModelControllerEventTypes.BRANCH_MOVED)


#: Dispatch glue: wire discriminator -> bus descriptor. The controller's drain
#: loop indexes this with ``event.type`` to re-publish each inbound server event
#: under its matching descriptor.
SERVER_EVENT_BY_TYPE: dict[ServerContextEventType, BusEvent[Any]] = {
    ServerContextEventType.RESPONSE_STARTED: RESPONSE_STARTED,
    ServerContextEventType.RESPONSE_UPDATED: RESPONSE_UPDATED,
    ServerContextEventType.RESPONSE_DONE: RESPONSE_DONE,
    ServerContextEventType.USER_ITEM_ADDED: USER_ITEM_ADDED,
    ServerContextEventType.USER_ITEM_UPDATED: USER_ITEM_UPDATED,
    ServerContextEventType.TOOL_RESULT_ADDED: TOOL_RESULT_ADDED,
    ServerContextEventType.COMPACTION_DONE: COMPACTION_DONE,
    ServerContextEventType.BRANCH_MOVED: BRANCH_MOVED,
}

#: Every controller bus event, in :class:`ModelControllerEventTypes` order, for
#: subscribers that want all of them (e.g. the pass-through stream producer).
ALL_EVENTS: tuple[BusEvent[Any], ...] = tuple(SERVER_EVENT_BY_TYPE.values())


__all__ = [
    "ModelControllerEventTypes",
    "RESPONSE_STARTED",
    "RESPONSE_UPDATED",
    "RESPONSE_DONE",
    "USER_ITEM_ADDED",
    "USER_ITEM_UPDATED",
    "TOOL_RESULT_ADDED",
    "COMPACTION_DONE",
    "BRANCH_MOVED",
]
