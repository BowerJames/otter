"""Construction, validation, and round-trip of the session entry model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from otter_ai_core.context import AssistantContextItem, Role, UserContextItem, UserMessage
from otter_ai_core.session_manager import (
    ActiveToolsChangeEntry,
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    CustomMessageEntry,
    LabelEntry,
    MessageEntry,
    MessageUpdateEntry,
    ModelChangeEntry,
    SessionEntry,
    SessionEntryType,
    SessionInfoEntry,
    ThinkingLevelChangeEntry,
)

# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _user_item(item_id: str = "u1", text: str = "hi") -> UserContextItem:
    return UserContextItem(
        id=item_id,
        message=UserMessage(role=Role.User, content=text, timestamp=1700000000000),
    )


def _assistant_item(item_id: str = "a1") -> AssistantContextItem:
    from otter_ai_core import AssistantMessage, StopReason, TextContent, Usage, UsageCost

    return AssistantContextItem(
        id=item_id,
        message=AssistantMessage(
            role=Role.Assistant,
            content=[TextContent(type="text", text="hello")],
            api="anthropic-messages",
            provider="anthropic",
            model="claude-3",
            usage=Usage(
                input=1,
                output=1,
                cache_read=0,
                cache_write=0,
                total_tokens=2,
                cost=UsageCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0),
            ),
            stop_reason=StopReason.Stop,
            timestamp=1700000000001,
        ),
    )


# --------------------------------------------------------------------------- #
# Type discriminator
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("entry_type", "value"),
    [
        (SessionEntryType.MESSAGE, "message"),
        (SessionEntryType.MESSAGE_UPDATE, "message_update"),
        (SessionEntryType.MODEL_CHANGE, "model_change"),
        (SessionEntryType.THINKING_LEVEL_CHANGE, "thinking_level_change"),
        (SessionEntryType.ACTIVE_TOOLS_CHANGE, "active_tools_change"),
        (SessionEntryType.COMPACTION, "compaction"),
        (SessionEntryType.BRANCH_SUMMARY, "branch_summary"),
        (SessionEntryType.CUSTOM, "custom"),
        (SessionEntryType.CUSTOM_MESSAGE, "custom_message"),
        (SessionEntryType.LABEL, "label"),
        (SessionEntryType.SESSION_INFO, "session_info"),
    ],
)
def test_entry_type_values(entry_type: SessionEntryType, value: str) -> None:
    assert entry_type.value == value
    assert entry_type == value  # StrEnum flattens to its value


def test_default_type_discriminators() -> None:
    """Each variant stamps its own ``type`` without the caller passing it."""
    assert (
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item()).type
        == SessionEntryType.MESSAGE
    )
    assert (
        ModelChangeEntry(
            id="2", parent_id="1", timestamp="t", provider="anthropic", model="claude-3"
        ).type
        == SessionEntryType.MODEL_CHANGE
    )
    assert (
        ThinkingLevelChangeEntry(id="3", parent_id="2", timestamp="t", thinking_level="high").type
        == SessionEntryType.THINKING_LEVEL_CHANGE
    )
    assert (
        ActiveToolsChangeEntry(
            id="4", parent_id="3", timestamp="t", active_tool_names=["search"]
        ).type
        == SessionEntryType.ACTIVE_TOOLS_CHANGE
    )
    assert (
        CustomMessageEntry(
            id="5", parent_id="4", timestamp="t", custom_type="note", content="x", display=True
        ).type
        == SessionEntryType.CUSTOM_MESSAGE
    )


# --------------------------------------------------------------------------- #
# MessageEntry / MessageUpdateEntry specifics
# --------------------------------------------------------------------------- #


def test_message_entry_carries_context_item() -> None:
    item = _user_item()
    entry = MessageEntry(id="1", parent_id=None, timestamp="2026-07-23T00:00:00Z", item=item)
    assert entry.item is item
    assert entry.item.id == "u1"


def test_message_update_entry_target_id_mirrors_item_id() -> None:
    revised = _user_item(item_id="u1", text="hi (revised)")
    entry = MessageUpdateEntry(
        id="2", parent_id="1", timestamp="2026-07-23T00:00:01Z", item=revised, target_item_id="u1"
    )
    assert entry.target_item_id == revised.id == "u1"


# --------------------------------------------------------------------------- #
# extra="forbid"
# --------------------------------------------------------------------------- #


def test_entry_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        MessageEntry(  # type: ignore[call-arg]
            id="1", parent_id=None, timestamp="t", item=_user_item(), bogus=123
        )


# --------------------------------------------------------------------------- #
# Discriminated-union JSON round-trip
# --------------------------------------------------------------------------- #


def _sample_of_every_type() -> list[SessionEntry]:
    return [
        MessageEntry(id="1", parent_id=None, timestamp="t1", item=_user_item()),
        MessageUpdateEntry(
            id="2", parent_id="1", timestamp="t2", item=_assistant_item(), target_item_id="a1"
        ),
        ModelChangeEntry(
            id="3", parent_id="2", timestamp="t3", provider="anthropic", model="claude"
        ),
        ThinkingLevelChangeEntry(id="4", parent_id="3", timestamp="t4", thinking_level="high"),
        ActiveToolsChangeEntry(id="5", parent_id="4", timestamp="t5", active_tool_names=["search"]),
        CompactionEntry(
            id="6",
            parent_id="5",
            timestamp="t6",
            summary="s",
            first_kept_entry_id="2",
            tokens_before=100,
        ),
        BranchSummaryEntry(id="7", parent_id="6", timestamp="t7", from_id="3", summary="b"),
        CustomEntry(id="8", parent_id="7", timestamp="t8", custom_type="note"),
        CustomMessageEntry(
            id="9", parent_id="8", timestamp="t9", custom_type="note", content="c", display=True
        ),
        LabelEntry(id="10", parent_id="9", timestamp="t10", target_id="1", label="pinned"),
        SessionInfoEntry(id="11", parent_id="10", timestamp="t11", name="my session"),
    ]


@pytest.mark.parametrize("entry", _sample_of_every_type())
def test_union_round_trip(entry: SessionEntry) -> None:
    import json

    from pydantic import TypeAdapter

    adapter: TypeAdapter[SessionEntry] = TypeAdapter(SessionEntry)
    raw = adapter.dump_json(entry)
    restored = adapter.validate_json(raw)
    assert restored == entry
    assert json.loads(raw)["type"] == entry.type.value  # both are str
