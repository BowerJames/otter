from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from otter_ai_core.data_models.context import (
    AssistantContextItem,
    ToolResultContextItem,
    Usage,
    UserContextItem,
)
from otter_ai_core.data_models.events.event import Event


class ServerContextEventType(StrEnum):
    RESPONSE_STARTED = "response.started"
    RESPONSE_UPDATED = "response.updated"
    RESPONSE_DONE = "response.done"
    USER_ITEM_ADDED = "user_item.added"
    USER_ITEM_UPDATED = "user_item.updated"
    TOOL_RESULT_ADDED = "tool_result_item.added"
    COMPACTION_DONE = "compaction.done"
    BRANCH_MOVED = "branch.moved"


class ResponseStarted(Event[ServerContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.RESPONSE_STARTED] = ServerContextEventType.RESPONSE_STARTED  # noqa: E501
    partial: AssistantContextItem


class ResponseUpdated(Event[ServerContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.RESPONSE_UPDATED] = ServerContextEventType.RESPONSE_UPDATED  # noqa: E501
    partial: AssistantContextItem


class ResponseDone(Event[ServerContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.RESPONSE_DONE] = ServerContextEventType.RESPONSE_DONE  # noqa: E501
    item: AssistantContextItem


class UserItemAdded(Event[ServerContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.USER_ITEM_ADDED] = ServerContextEventType.USER_ITEM_ADDED  # noqa: E501
    item: UserContextItem


class UserItemUpdated(Event[ServerContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.USER_ITEM_UPDATED] = (
        ServerContextEventType.USER_ITEM_UPDATED
    )  # noqa: E501
    item: UserContextItem


class ToolResultAdded(Event[ServerContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.TOOL_RESULT_ADDED] = (
        ServerContextEventType.TOOL_RESULT_ADDED
    )  # noqa: E501
    item: ToolResultContextItem


class CompactionDone(Event[ServerContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.COMPACTION_DONE] = ServerContextEventType.COMPACTION_DONE  # noqa: E501
    summary: str | None = None
    summary_item_id: str | None = None
    first_kept_item_id: str | None = None
    removed_item_ids: list[str] | None = None
    tokens_before: int | None = None
    usage: Usage | None = None
    error_message: str | None = None


class BranchMoved(Event[ServerContextEventType]):
    model_config = ConfigDict(extra="forbid")

    type: Literal[ServerContextEventType.BRANCH_MOVED] = ServerContextEventType.BRANCH_MOVED  # noqa: E501
    at_item_id: str
    removed_item_ids: list[str] | None = None
    summary_item_id: str | None = None
    usage: Usage | None = None
    error_message: str | None = None


#: Discriminated union of all server→client (inbound) model-connection events.
ServerContextEvent = Annotated[
    ResponseStarted
    | ResponseUpdated
    | ResponseDone
    | UserItemAdded
    | UserItemUpdated
    | ToolResultAdded
    | CompactionDone
    | BranchMoved,
    Field(discriminator="type"),
]
