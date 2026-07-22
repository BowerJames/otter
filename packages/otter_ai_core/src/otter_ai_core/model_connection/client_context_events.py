"""Client→server events for a model connection.

This module models the outbound events a client pushes into a model
connection — the ``TClient`` of
:class:`otter_ai_core.connection.ConnectionClient` / the
:data:`~otter_ai_core.model_connection.ModelConnectionClient` typed alias. It
is **data-only**: no transport, no provider registry, no dispatch. Only the
Pydantic v2 data structures a client pushes and a server (transport pump)
drains.

The protocol is otter's general model-connection event structure, partly
modelled on the OpenAI Responses / Realtime client-event families (e.g.
``response.create``). It is a single discriminated union over ``type``.

Producer contract
-----------------
A client pushes these events to drive a connection: it appends conversation
input (``user_message.add`` / ``tool_result.add``), asks the server to generate
(``response.create``), or asks it to stop the current generation
(``response.abort``). ``response.create`` may also carry advisory per-request
``model`` / ``thinking_level`` overrides.

Two additional ops target **stateful** connections (those that accumulate live
conversation state across turns): ``compaction.create`` asks the server to
collapse its live history in place, and ``branch.move`` asks it to truncate the
live conversation to an earlier item. Stateless providers ignore these (they
rebuild context each turn); the matching server→client events
(``compaction.done`` / ``branch.moved``) live in
:mod:`otter_ai_core.model_connection.server_context_events`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from otter_ai_core.context import ToolResultMessage, UserMessage
from otter_ai_core.event import Event
from otter_ai_core.provider_api_model_options import ThinkingLevel


class ClientContextEventType(StrEnum):
    """The ``type`` field of a client→server model-connection event."""

    ADD_USER_MESSAGE = "user_message.add"
    ADD_TOOL_RESULT_MESSAGE = "tool_result.add"
    CREATE_RESPONSE = "response.create"
    ABORT_RESPONSE = "response.abort"
    CREATE_COMPACTION = "compaction.create"
    BRANCH_MOVE = "branch.move"


class AddUserMessage(Event[ClientContextEventType]):
    """Append a user message to the conversation before a ``response.create``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.ADD_USER_MESSAGE] = ClientContextEventType.ADD_USER_MESSAGE  # noqa: E501
    message: UserMessage


class AddToolResultMessage(Event[ClientContextEventType]):
    """Append a tool-result message to the conversation before a ``response.create``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.ADD_TOOL_RESULT_MESSAGE] = (
        ClientContextEventType.ADD_TOOL_RESULT_MESSAGE
    )  # noqa: E501
    message: ToolResultMessage


class CreateResponse(Event[ClientContextEventType]):
    """Ask the server to generate the next assistant response.

    ``model`` / ``thinking_level`` are *advisory per-request overrides*: a
    transport honors what its API allows (e.g. an OpenAI-Realtime-style
    ``response.create`` that carries per-response params). ``None`` (default)
    means "use the connection's session-bound default". This is the desync-free
    path for model/thinking changes on stateless providers — the driver re-sends
    the session's current derived value on every ``response.create``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.CREATE_RESPONSE] = ClientContextEventType.CREATE_RESPONSE  # noqa: E501
    model: str | None = None
    thinking_level: ThinkingLevel | None = None


class AbortResponse(Event[ClientContextEventType]):
    """Ask the server to abort the current response generation."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.ABORT_RESPONSE] = ClientContextEventType.ABORT_RESPONSE  # noqa: E501


class CreateCompaction(Event[ClientContextEventType]):
    """Ask a stateful server to compact its live conversation history in place.

    The server generates a summary (it owns the model) **unless** ``summary`` is
    set, in which case it skips generation and applies the client-supplied
    summary. ``first_kept_item_id`` retains live items from that server item id
    onward; the pre-compaction items are dropped from the live view. The
    matching server→client confirm is :class:`CompactionDone`.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.CREATE_COMPACTION] = (
        ClientContextEventType.CREATE_COMPACTION
    )  # noqa: E501
    first_kept_item_id: str | None = None
    custom_instructions: str | None = None
    summary: str | None = None


class BranchMove(Event[ClientContextEventType]):
    """Ask a stateful server to truncate its live conversation to an earlier item.

    ``at_item_id`` becomes the new live head; items after it are dropped from
    the live view (the durable branch tree lives in the session layer). An
    optional ``summary`` may be injected at the branch point. The matching
    server→client confirm is :class:`BranchMoved`.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.BRANCH_MOVE] = ClientContextEventType.BRANCH_MOVE  # noqa: E501
    at_item_id: str
    summary: str | None = None


#: Discriminated union of all client→server (outbound) model-connection events.
ClientContextEvent = Annotated[
    AddUserMessage
    | AddToolResultMessage
    | CreateResponse
    | AbortResponse
    | CreateCompaction
    | BranchMove,
    Field(discriminator="type"),
]
