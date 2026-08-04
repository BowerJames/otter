from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.data_models.context import ContextItem, Usage, UserContent
from otter_ai_core.data_models.provider import ThinkingLevel


class SessionEntryType(StrEnum):
    MESSAGE = "message"
    #: Append-only amendment of a previously-recorded item (§8 of the issue spec).
    MESSAGE_UPDATE = "message_update"
    MODEL_CHANGE = "model_change"
    THINKING_LEVEL_CHANGE = "thinking_level_change"
    ACTIVE_TOOLS_CHANGE = "active_tools_change"
    COMPACTION = "compaction"
    BRANCH_SUMMARY = "branch_summary"
    #: Extension state, NOT projected to context.
    CUSTOM = "custom"
    #: Extension-injected content, IN context (projected as a user message).
    CUSTOM_MESSAGE = "custom_message"
    LABEL = "label"
    #: E.g. display name.
    SESSION_INFO = "session_info"


class SessionEntryBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    parent_id: str | None
    #: ISO-8601 UTC (cf. ``otter-ai-logging``).
    timestamp: str


class MessageEntry(SessionEntryBase):
    type: Literal[SessionEntryType.MESSAGE] = SessionEntryType.MESSAGE
    item: ContextItem


class MessageUpdateEntry(SessionEntryBase):
    type: Literal[SessionEntryType.MESSAGE_UPDATE] = SessionEntryType.MESSAGE_UPDATE
    item: ContextItem
    target_item_id: str  # == item.id


class ModelChangeEntry(SessionEntryBase):
    type: Literal[SessionEntryType.MODEL_CHANGE] = SessionEntryType.MODEL_CHANGE
    #: ``str`` (NOT ``KnownProviders``) so a runtime-registered provider round-trips
    #: — see §7 of the issue spec (derivation falls back to ``AssistantMessage.provider``).
    provider: str
    model: str


class ThinkingLevelChangeEntry(SessionEntryBase):
    type: Literal[SessionEntryType.THINKING_LEVEL_CHANGE] = SessionEntryType.THINKING_LEVEL_CHANGE  # noqa: E501
    thinking_level: ThinkingLevel


class ActiveToolsChangeEntry(SessionEntryBase):
    type: Literal[SessionEntryType.ACTIVE_TOOLS_CHANGE] = SessionEntryType.ACTIVE_TOOLS_CHANGE  # noqa: E501
    active_tool_names: list[str]


class CompactionEntry(SessionEntryBase):
    type: Literal[SessionEntryType.COMPACTION] = SessionEntryType.COMPACTION
    summary: str
    first_kept_entry_id: str | None
    tokens_before: int
    # CONTEXT ITEMS (not Messages), so the retained slice keeps its real server
    # ids/timestamps and can be revised later (§8). Materialized by
    # ``entries_to_items`` in ``projection.py``; NOT part of the transformed
    # entry list.
    retained_tail: list[ContextItem] | None = None
    details: Any | None = None  # impl/extension-specific (Any — see module docstring)
    usage: Usage | None = None
    from_hook: bool = False  # True if extension-supplied


class BranchSummaryEntry(SessionEntryBase):
    type: Literal[SessionEntryType.BRANCH_SUMMARY] = SessionEntryType.BRANCH_SUMMARY
    #: ``None`` == branched to the root.
    from_id: str | None
    summary: str
    details: Any | None = None
    usage: Usage | None = None
    from_hook: bool = False


class CustomEntry(SessionEntryBase):
    type: Literal[SessionEntryType.CUSTOM] = SessionEntryType.CUSTOM
    custom_type: str
    data: Any | None = None


class CustomMessageEntry(SessionEntryBase):
    type: Literal[SessionEntryType.CUSTOM_MESSAGE] = SessionEntryType.CUSTOM_MESSAGE
    custom_type: str
    content: str | list[UserContent]
    details: Any | None = None
    display: bool


class LabelEntry(SessionEntryBase):
    type: Literal[SessionEntryType.LABEL] = SessionEntryType.LABEL
    target_id: str
    label: str | None  # None/empty clears


class SessionInfoEntry(SessionEntryBase):
    type: Literal[SessionEntryType.SESSION_INFO] = SessionEntryType.SESSION_INFO
    name: str | None


#: Discriminated union of all session entries. The leaf pointer is NOT a variant
#: here — see the module docstring (``pi`` leaks a ``LeafEntry``; otter does not).
SessionEntry = Annotated[
    MessageEntry
    | MessageUpdateEntry
    | ModelChangeEntry
    | ThinkingLevelChangeEntry
    | ActiveToolsChangeEntry
    | CompactionEntry
    | BranchSummaryEntry
    | CustomEntry
    | CustomMessageEntry
    | LabelEntry
    | SessionInfoEntry,
    Field(discriminator="type"),
]


__all__ = [
    "SessionEntryType",
    "SessionEntryBase",
    "MessageEntry",
    "MessageUpdateEntry",
    "ModelChangeEntry",
    "ThinkingLevelChangeEntry",
    "ActiveToolsChangeEntry",
    "CompactionEntry",
    "BranchSummaryEntry",
    "CustomEntry",
    "CustomMessageEntry",
    "LabelEntry",
    "SessionInfoEntry",
    "SessionEntry",
]
