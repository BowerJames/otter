"""Bus events emitted by :class:`~otter_ai_core.model_controller.ModelController`.

This module is the fan-out counterpart to :mod:`otter_ai_core.agent_loop.hooks`:
a dedicated :class:`~enum.StrEnum` (:class:`ModelControllerEventTypes`)
centralizes the event *name strings* so they are discoverable rather than
magic-string literals, and the typed :class:`~otter_ai_core.bus.BusEvent`
descriptors (built from the enum members) are what callers
:meth:`~otter_ai_core.bus.Bus.subscribe` /
:meth:`~otter_ai_core.bus.Bus.publish` against.

Why an enum *and* descriptors
-----------------------------
A :class:`~enum.StrEnum` cannot carry per-member type parameters, so the type
checker could not recover the payload type from an enum-keyed ``publish``.
Instead the enum here centralizes the name strings and the typed
:class:`~otter_ai_core.bus.BusEvent` singleton (built from the enum member)
remains the value callers register against. Because :class:`~enum.StrEnum`
members are :class:`str` instances that hash and compare equal to their value,
``BusEvent(ModelControllerEventTypes.X)`` keys identically to
``BusEvent("x")`` in the :class:`~otter_ai_core.bus.Bus` registry — exactly the
split :mod:`otter_ai_core.agent_loop.hooks` established for hooks.

Drift-proof values
------------------
The controller re-publishes every inbound server event under its matching bus
event, so :class:`ModelControllerEventTypes` mirrors
:class:`~otter_ai_core.model_connection.ServerContextEventType` 1:1. Each
member's value *references* the corresponding wire-enum member
(``RESPONSE_DONE = ServerContextEventType.RESPONSE_DONE``) rather than
duplicating the literal, so the two enums cannot drift apart. StrEnum flattens
the referenced member to its string, so ``str(...)``, ``.value``, hashing, and
``==`` all behave as the plain wire string.

Dispatch glue
-------------
The controller's drain loop receives an inbound
:data:`~otter_ai_core.model_connection.ServerContextEvent` and re-publishes it
under the matching descriptor; :data:`SERVER_EVENT_BY_TYPE` maps the wire
discriminator to that descriptor, and :data:`ALL_EVENTS` enumerates every
descriptor (for pass-through subscribers such as
:mod:`otter_ai_core.model_controller.stream`). These are internal glue, not part
of the public event surface (not in :data:`__all__`).
"""

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
    """The ``name`` of a bus event emitted by :class:`ModelController`.

    Values reference :class:`~otter_ai_core.model_connection.ServerContextEventType`
    members 1:1 (the controller re-publishes every inbound server event under
    its matching bus event), so the two enums cannot drift apart. The enum
    centralizes the name strings; the typed
    :class:`~otter_ai_core.bus.BusEvent` descriptors below (built from its
    members) are what callers subscribe/publish with.
    """

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
