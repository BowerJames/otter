"""The append-only session entry tree (the persisted data model).

A session is an append-only tree of :data:`SessionEntry` s, each
``{id, parent_id, timestamp, type}`` — modelled like otter's other discriminated
model families: a :class:`SessionEntryType` :class:`~enum.StrEnum` plus Pydantic
variants narrowing ``type`` to a literal (cf.
``model_connection/{client,server}_context_events.py``). Every variant sets
``model_config = ConfigDict(extra="forbid")``, matching the repo's other Pydantic
models.

**Tree ids are opaque and store-generated**, unique *within the session* — the
store's ``create_entry_id()`` produces them (``pi``'s choice). A
:class:`MessageEntry` *carries* a full :class:`~otter_ai_core.context.ContextItem`
(which has its own caller/server-assigned ``id``); the tree id and the item id are
**distinct**. This is what makes append-only item updates clean: a revision and
its original share the *item* id but get *distinct tree* ids, and
provider-assigned item ids — which are not guaranteed tree-safe — never
participate in tree topology.

Opaque extension payloads (``details`` / ``data``) are typed ``Any | None`` to
match the repo convention for JSON payloads
(:class:`~otter_ai_core.context.ToolResultMessage.details`,
:class:`~otter_ai_core.context.ToolCall.arguments`) — not ``object``.
``None`` means "absent"; ``Any`` round-trips arbitrary JSON through Pydantic v2.

There is deliberately **no ``LEAF`` variant in the union** (unlike ``pi``, which
leaks a ``LeafEntry`` into the union): the leaf pointer is abstracted by the
store (``leaf_id()`` / ``set_leaf_id()``) and is an implementation detail a
backend may persist internally.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.context import ContextItem, Usage, UserContent
from otter_ai_core.provider_api_model_options import ThinkingLevel


class SessionEntryType(StrEnum):
    """The ``type`` field of a :data:`SessionEntry`."""

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
    """Tree identity shared by every entry.

    Concrete variants narrow ``type`` to a literal member and add their
    payload fields. The leaf pointer is NOT a union variant (see the module
    docstring) — backends persist it internally and expose it via the store.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    parent_id: str | None
    #: ISO-8601 UTC (cf. ``otter-ai-logging``).
    timestamp: str


class MessageEntry(SessionEntryBase):
    """Records a conversation item (initial add). Carries a full :class:`ContextItem`."""

    type: Literal[SessionEntryType.MESSAGE] = SessionEntryType.MESSAGE
    item: ContextItem


class MessageUpdateEntry(SessionEntryBase):
    """Append-only amendment of a previously-recorded item (§8 of the issue spec).

    Carries the revised :class:`ContextItem` (same server item id, new content +
    timestamp). Projection folds revisions by item id, keeping the latest item's
    message at the item's first-seen position. ``target_item_id`` mirrors
    ``item.id`` (kept explicit for clarity/validation). Mirrors the server
    ``user_item.updated`` event; generalized to any :class:`ContextItem` role.
    """

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
    """Extension state, NOT projected to context. ``data`` loosely typed for v1."""

    type: Literal[SessionEntryType.CUSTOM] = SessionEntryType.CUSTOM
    custom_type: str
    data: Any | None = None


class CustomMessageEntry(SessionEntryBase):
    """Extension-injected content, IN context (projected as a user message).

    ``display`` is inert UI metadata (whether a renderer should show the raw
    custom payload). It is NOT a projection gate: a :class:`CustomMessageEntry`
    is always projected into context (mirroring ``pi``'s ``convertToLlm``).
    """

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
