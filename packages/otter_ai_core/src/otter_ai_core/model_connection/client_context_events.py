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
input (``user_message.add`` / ``tool_result.add``) and then asks the server to
generate (``response.create``). The matching server→client events live in
:mod:`otter_ai_core.model_connection.server_context_events`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.context import ToolResultMessage, UserMessage


class AddUserMessage(BaseModel):
    """Append a user message to the conversation before a ``response.create``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["user_message.add"] = "user_message.add"
    message: UserMessage


class AddToolResultMessage(BaseModel):
    """Append a tool-result message to the conversation before a ``response.create``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_result.add"] = "tool_result.add"
    message: ToolResultMessage


class CreateResponse(BaseModel):
    """Ask the server to generate the next assistant response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["response.create"] = "response.create"


#: Discriminated union of all client→server (outbound) model-connection events.
ClientContextEvent = Annotated[
    AddUserMessage | AddToolResultMessage | CreateResponse,
    Field(discriminator="type"),
]
