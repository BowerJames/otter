"""Server→client events for a model connection.

This module models the inbound events a server (transport pump) pushes to the
client over a model connection — the ``TBackend`` of
:class:`otter_ai_core.connection.ConnectionBackend` / the
:data:`~otter_ai_core.model_connection.ModelConnectionBackend` typed alias.
It is **data-only**: no transport, no provider registry, no dispatch. Only the
Pydantic v2 data structures a server pushes and a client iterates.

The protocol is otter's general model-connection event structure, partly
modelled on the OpenAI Responses / Realtime server-event families (e.g.
``response.created`` / ``response.done``). It is a single discriminated union
over ``type``.

Item vs. message
----------------
Where the client→server events carry raw messages
(see :mod:`otter_ai_core.model_connection.client_context_events`), these
server→client events carry *context items* — messages tagged with the
server-assigned ``id`` the client uses to place them in a
:class:`~otter_ai_core.context.Context`. ``response.updated`` events carry an in-flight
``partial`` :class:`~otter_ai_core.context.AssistantContextItem` (its
underlying message's ``stop_reason`` is ``None`` until the terminal
``response.done``).

Producer contract
-----------------
For a single ``response.create`` the server emits ``response.started`` (with
an empty/partial assistant item), zero or more ``response.updated`` snapshots,
then a terminal ``response.done`` carrying the final assistant item. Out-of-
band, the server emits ``user_item.added`` / ``user_item.updated`` /
``tool_result_item.added`` to echo back the items it accepted or amended:
``user_item.updated`` signals that an existing user item was amended (e.g. an
asynchronously-transcribed audio item revised after it was first added, as in
the OpenAI Realtime API), so a client must refresh any local copy.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.context import (
    AssistantContextItem,
    ToolResultContextItem,
    UserContextItem,
)


class ServerContextEventType(StrEnum):
    """The ``type`` field of a server→client model-connection event."""

    RESPONSE_STARTED = "response.started"
    RESPONSE_UPDATED = "response.updated"
    RESPONSE_DONE = "response.done"
    USER_ITEM_ADDED = "user_item.added"
    USER_ITEM_UPDATED = "user_item.updated"
    TOOL_RESULT_ADDED = "tool_result_item.added"


class ResponseStarted(BaseModel):
    """A response generation has started. ``partial`` is the empty-start item."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.RESPONSE_STARTED] = (
        ServerContextEventType.RESPONSE_STARTED
    )  # noqa: E501
    partial: AssistantContextItem


class ResponseUpdated(BaseModel):
    """An update to the in-progress assistant item.

    ``partial`` is a full snapshot of the in-progress
    :class:`~otter_ai_core.context.AssistantContextItem` (its message's
    ``stop_reason`` is ``None`` while in flight).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.RESPONSE_UPDATED] = (
        ServerContextEventType.RESPONSE_UPDATED
    )  # noqa: E501
    partial: AssistantContextItem


class ResponseDone(BaseModel):
    """Response generation completed. ``item`` is the final assistant item."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.RESPONSE_DONE] = (
        ServerContextEventType.RESPONSE_DONE
    )  # noqa: E501
    item: AssistantContextItem


class UserItemAdded(BaseModel):
    """The server accepted a user message and assigned it an item ``id``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.USER_ITEM_ADDED] = (
        ServerContextEventType.USER_ITEM_ADDED
    )  # noqa: E501
    item: UserContextItem


class UserItemUpdated(BaseModel):
    """A previously-added user item was amended; refresh any local copy.

    Signals that an existing :class:`~otter_ai_core.context.UserContextItem`
    was updated server-side — e.g. an asynchronously-transcribed audio item
    revised after it was first added (as in the OpenAI Realtime API) — so a
    client holding a local copy of the item must refresh it.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.USER_ITEM_UPDATED] = (
        ServerContextEventType.USER_ITEM_UPDATED
    )  # noqa: E501
    item: UserContextItem


class ToolResultAdded(BaseModel):
    """The server accepted a tool result and assigned it an item ``id``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.TOOL_RESULT_ADDED] = (
        ServerContextEventType.TOOL_RESULT_ADDED
    )  # noqa: E501
    item: ToolResultContextItem


#: Discriminated union of all server→client (inbound) model-connection events.
ServerContextEvent = Annotated[
    ResponseStarted
    | ResponseUpdated
    | ResponseDone
    | UserItemAdded
    | UserItemUpdated
    | ToolResultAdded,
    Field(discriminator="type"),
]
