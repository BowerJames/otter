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
(``response.abort``). The matching server→client events live in
:mod:`otter_ai_core.model_connection.server_context_events`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.context import ToolResultMessage, UserMessage


class ClientContextEventType(StrEnum):
    """The ``type`` field of a client→server model-connection event."""

    ADD_USER_MESSAGE = "user_message.add"
    ADD_TOOL_RESULT_MESSAGE = "tool_result.add"
    CREATE_RESPONSE = "response.create"
    ABORT_RESPONSE = "response.abort"


class AddUserMessage(BaseModel):
    """Append a user message to the conversation before a ``response.create``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.ADD_USER_MESSAGE] = (
        ClientContextEventType.ADD_USER_MESSAGE
    )  # noqa: E501
    message: UserMessage


class AddToolResultMessage(BaseModel):
    """Append a tool-result message to the conversation before a ``response.create``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.ADD_TOOL_RESULT_MESSAGE] = (
        ClientContextEventType.ADD_TOOL_RESULT_MESSAGE
    )  # noqa: E501
    message: ToolResultMessage


class CreateResponse(BaseModel):
    """Ask the server to generate the next assistant response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.CREATE_RESPONSE] = (
        ClientContextEventType.CREATE_RESPONSE
    )  # noqa: E501


class AbortResponse(BaseModel):
    """Ask the server to abort the current response generation."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.ABORT_RESPONSE] = (
        ClientContextEventType.ABORT_RESPONSE
    )  # noqa: E501


#: Discriminated union of all client→server (outbound) model-connection events.
ClientContextEvent = Annotated[
    AddUserMessage | AddToolResultMessage | CreateResponse | AbortResponse,
    Field(discriminator="type"),
]
