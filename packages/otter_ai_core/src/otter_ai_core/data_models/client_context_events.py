from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from otter_ai_core.context import ToolResultMessage, UserMessage
from otter_ai_core.event import Event
from otter_ai_core.provider_api_model_options import ThinkingLevel


class ClientContextEventType(StrEnum):
    ADD_USER_MESSAGE = "user_message.add"
    ADD_TOOL_RESULT_MESSAGE = "tool_result.add"
    CREATE_RESPONSE = "response.create"
    ABORT_RESPONSE = "response.abort"
    CREATE_COMPACTION = "compaction.create"
    BRANCH_MOVE = "branch.move"


class AddUserMessage(Event[ClientContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.ADD_USER_MESSAGE] = ClientContextEventType.ADD_USER_MESSAGE  # noqa: E501
    message: UserMessage


class AddToolResultMessage(Event[ClientContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.ADD_TOOL_RESULT_MESSAGE] = (
        ClientContextEventType.ADD_TOOL_RESULT_MESSAGE
    )  # noqa: E501
    message: ToolResultMessage


class CreateResponse(Event[ClientContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.CREATE_RESPONSE] = ClientContextEventType.CREATE_RESPONSE  # noqa: E501
    model: str | None = None
    thinking_level: ThinkingLevel | None = None


class AbortResponse(Event[ClientContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.ABORT_RESPONSE] = ClientContextEventType.ABORT_RESPONSE  # noqa: E501


class CreateCompaction(Event[ClientContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.CREATE_COMPACTION] = (
        ClientContextEventType.CREATE_COMPACTION
    )  # noqa: E501
    first_kept_item_id: str | None = None
    custom_instructions: str | None = None
    summary: str | None = None


class BranchMove(Event[ClientContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientContextEventType.BRANCH_MOVE] = ClientContextEventType.BRANCH_MOVE  # noqa: E501
    at_item_id: str
    summary: str | None = None


#: A client→server event that appends conversation input before a generation.
InputEvent = AddUserMessage | AddToolResultMessage

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
