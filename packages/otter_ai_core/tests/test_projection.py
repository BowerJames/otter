"""Pure projection functions over hand-built entry lists.

No async, no store, no event loop — the lightweight read path. Exercises
``apply_compaction_transform`` / ``entries_to_items`` / ``apply_updates`` /
``derive_state`` / ``project`` directly (issue spec §7).
"""

from __future__ import annotations

from otter_ai_core import (
    AssistantContextItem,
    AssistantMessage,
    StopReason,
    TextContent,
    ToolResultContextItem,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserContent,
    UserContextItem,
    UserMessage,
)
from otter_ai_core.context import Role
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
    SessionInfoEntry,
    SessionProjection,
    ThinkingLevelChangeEntry,
    apply_compaction_transform,
    apply_updates,
    derive_state,
    entries_to_items,
    project,
)

TS = "2026-07-23T00:00:00Z"


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _zero_cost() -> UsageCost:
    return UsageCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0)


def _usage(n: int = 1) -> Usage:
    return Usage(
        input=n, output=n, cache_read=0, cache_write=0, total_tokens=2 * n, cost=_zero_cost()
    )


def _user_item(item_id: str, text: str, ts: int = 1) -> UserContextItem:
    return UserContextItem(
        id=item_id, message=UserMessage(role=Role.User, content=text, timestamp=ts)
    )


def _tool_result_item(item_id: str) -> ToolResultContextItem:
    return ToolResultContextItem(
        id=item_id,
        message=ToolResultMessage(
            role=Role.ToolResult,
            tool_call_id="c1",
            tool_name="search",
            content=[TextContent(type="text", text="r")],
            is_error=False,
            timestamp=1,
        ),
    )


def _assistant_item(
    item_id: str, *, provider: str = "anthropic", model: str = "claude-3", ts: int = 2
) -> AssistantContextItem:
    return AssistantContextItem(
        id=item_id,
        message=AssistantMessage(
            role=Role.Assistant,
            content=[TextContent(type="text", text="ok")],
            api="anthropic-messages",
            provider=provider,
            model=model,
            usage=_usage(),
            stop_reason=StopReason.Stop,
            timestamp=ts,
        ),
    )


# --------------------------------------------------------------------------- #
# apply_compaction_transform
# --------------------------------------------------------------------------- #


def test_transform_no_compaction_returns_copy() -> None:
    path: list[SessionEntry] = [
        MessageEntry(id="1", parent_id=None, timestamp=TS, item=_user_item("u1", "a")),
        MessageEntry(id="2", parent_id="1", timestamp=TS, item=_user_item("u2", "b")),
    ]
    out = apply_compaction_transform(path)
    assert out == path
    assert out is not path  # a copy, not the same list


def test_transform_with_retained_tail_drops_pre_compaction_entries() -> None:
    path: list[SessionEntry] = [
        MessageEntry(id="1", parent_id=None, timestamp=TS, item=_user_item("u1", "x")),
        MessageEntry(id="2", parent_id="1", timestamp=TS, item=_user_item("u2", "y")),
        CompactionEntry(
            id="c",
            parent_id="2",
            timestamp=TS,
            summary="sum",
            first_kept_entry_id=None,
            tokens_before=10,
            retained_tail=[_user_item("u2", "y")],
        ),
        MessageEntry(id="3", parent_id="c", timestamp=TS, item=_user_item("u3", "z")),
    ]
    out = apply_compaction_transform(path)
    assert [e.id for e in out] == ["c", "3"]


def test_transform_with_first_kept_entry_id_keeps_window() -> None:
    path: list[SessionEntry] = [
        MessageEntry(id="1", parent_id=None, timestamp=TS, item=_user_item("u1", "x")),
        MessageEntry(id="2", parent_id="1", timestamp=TS, item=_user_item("u2", "y")),
        MessageEntry(id="3", parent_id="2", timestamp=TS, item=_user_item("u3", "z")),
        CompactionEntry(
            id="c",
            parent_id="3",
            timestamp=TS,
            summary="sum",
            first_kept_entry_id="2",
            tokens_before=10,
        ),
        MessageEntry(id="4", parent_id="c", timestamp=TS, item=_user_item("u4", "w")),
    ]
    out = apply_compaction_transform(path)
    # [compaction] + kept window [2,3] + post [4]
    assert [e.id for e in out] == ["c", "2", "3", "4"]


def test_transform_latest_compaction_wins() -> None:
    path: list[SessionEntry] = [
        MessageEntry(id="1", parent_id=None, timestamp=TS, item=_user_item("u1", "x")),
        CompactionEntry(
            id="c1",
            parent_id="1",
            timestamp=TS,
            summary="s1",
            first_kept_entry_id=None,
            tokens_before=5,
        ),
        MessageEntry(id="2", parent_id="c1", timestamp=TS, item=_user_item("u2", "y")),
        CompactionEntry(
            id="c2",
            parent_id="2",
            timestamp=TS,
            summary="s2",
            first_kept_entry_id=None,
            tokens_before=7,
        ),
        MessageEntry(id="3", parent_id="c2", timestamp=TS, item=_user_item("u3", "z")),
    ]
    out = apply_compaction_transform(path)
    assert [e.id for e in out] == ["c2", "3"]


# --------------------------------------------------------------------------- #
# entries_to_items
# --------------------------------------------------------------------------- #


def test_entries_to_items_message_and_update() -> None:
    items = entries_to_items(
        [
            MessageEntry(id="1", parent_id=None, timestamp=TS, item=_user_item("u1", "a")),
            MessageUpdateEntry(
                id="2",
                parent_id="1",
                timestamp=TS,
                item=_user_item("u1", "a-revised"),
                target_item_id="u1",
            ),
        ]
    )
    assert [i.id for i in items] == ["u1", "u1"]  # apply_updates folds these later


def test_entries_to_items_compaction_expands_retained_tail() -> None:
    retained = [_user_item("u2", "y"), _assistant_item("a1")]
    items = entries_to_items(
        [
            CompactionEntry(
                id="c",
                parent_id=None,
                timestamp=TS,
                summary="sum",
                first_kept_entry_id=None,
                tokens_before=10,
                retained_tail=retained,
            ),
        ]
    )
    assert len(items) == 3
    summary_item = items[0]
    assert isinstance(summary_item, UserContextItem)
    assert isinstance(summary_item.message.content, str)
    assert summary_item.message.content == "[compaction-summary]\n\nsum"
    assert summary_item.id == "c"  # synthesized id = tree entry id
    assert items[1:] == retained  # retained tail verbatim


def test_entries_to_items_branch_summary_marker() -> None:
    items = entries_to_items(
        [
            BranchSummaryEntry(
                id="b", parent_id=None, timestamp=TS, from_id="2", summary="the branch"
            )
        ]
    )
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, UserContextItem)
    assert isinstance(item.message.content, str)
    assert item.message.content == "[branch-summary:]\nthe branch]"
    assert item.id == "b"


def test_entries_to_items_custom_message_string_content() -> None:
    items = entries_to_items(
        [
            CustomMessageEntry(
                id="cm",
                parent_id=None,
                timestamp=TS,
                custom_type="note",
                content="hello",
                display=True,
            )
        ]
    )
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, UserContextItem)
    assert item.message.content == "hello"
    assert item.id == "cm"


def test_entries_to_items_custom_message_block_content() -> None:
    blocks: list[UserContent] = [TextContent(type="text", text="hi")]
    items = entries_to_items(
        [
            CustomMessageEntry(
                id="cm",
                parent_id=None,
                timestamp=TS,
                custom_type="note",
                content=blocks,
                display=False,
            )
        ]
    )
    assert items[0].message.content == blocks  # display is inert — still projected


def test_entries_to_items_ignores_non_message_entries() -> None:
    items = entries_to_items(
        [
            ModelChangeEntry(
                id="m", parent_id=None, timestamp=TS, provider="anthropic", model="claude"
            ),
            ThinkingLevelChangeEntry(id="t", parent_id="m", timestamp=TS, thinking_level="high"),
            ActiveToolsChangeEntry(
                id="a", parent_id="t", timestamp=TS, active_tool_names=["search"]
            ),
            CustomEntry(id="cu", parent_id="a", timestamp=TS, custom_type="note"),
            LabelEntry(id="l", parent_id="cu", timestamp=TS, target_id="m", label="pinned"),
            SessionInfoEntry(id="s", parent_id="l", timestamp=TS, name="name"),
        ]
    )
    assert items == []


def test_entries_to_items_synthesized_timestamp_is_ms() -> None:
    items = entries_to_items(
        [
            CustomMessageEntry(
                id="cm",
                parent_id=None,
                timestamp="2026-07-23T00:00:00Z",
                custom_type="n",
                content="x",
                display=True,
            )
        ]
    )
    assert isinstance(items[0].message.timestamp, int)
    assert items[0].message.timestamp > 1_700_000_000_000


# --------------------------------------------------------------------------- #
# apply_updates
# --------------------------------------------------------------------------- #


def test_apply_updates_latest_at_first_position() -> None:
    items = [
        _user_item("u1", "orig"),
        _user_item("u1", "revised"),
    ]
    out = apply_updates(items)
    assert len(out) == 1
    assert out[0].id == "u1"
    assert isinstance(out[0].message, UserMessage)
    assert out[0].message.content == "revised"  # latest content...
    assert out[0].message.timestamp == 1  # first-occurrence position


def test_apply_updates_keeps_distinct_ids_in_order() -> None:
    items = [_user_item("u1", "a"), _user_item("u2", "b"), _user_item("u3", "c")]
    out = apply_updates(items)
    assert [i.id for i in out] == ["u1", "u2", "u3"]


def test_apply_updates_orphan_revision_stands_alone() -> None:
    # A revision whose original is NOT on the path stands at its own position.
    items = [
        _user_item("u1", "a"),
        _user_item("u9", "orphan-revised"),  # no earlier u9
    ]
    out = apply_updates(items)
    assert [i.id for i in out] == ["u1", "u9"]
    assert isinstance(out[1].message, UserMessage)
    assert out[1].message.content == "orphan-revised"


def test_apply_updates_revision_of_retained_tail_item() -> None:
    retained = _user_item("u2", "orig")
    items = entries_to_items(
        [
            CompactionEntry(
                id="c",
                parent_id=None,
                timestamp=TS,
                summary="sum",
                first_kept_entry_id=None,
                tokens_before=10,
                retained_tail=[retained],
            ),
            MessageUpdateEntry(
                id="u",
                parent_id="c",
                timestamp=TS,
                item=_user_item("u2", "folded"),
                target_item_id="u2",
            ),
        ]
    )
    out = apply_updates(items)
    # The summary item (id "c") + the folded u2 (latest content) at its first position.
    assert [i.id for i in out] == ["c", "u2"]
    folded = out[1]
    assert isinstance(folded.message, UserMessage)
    assert folded.message.content == "folded"


def test_apply_updates_synthesized_ids_never_collapse() -> None:
    items = entries_to_items(
        [
            BranchSummaryEntry(id="b1", parent_id=None, timestamp=TS, from_id=None, summary="s1"),
            BranchSummaryEntry(id="b2", parent_id="b1", timestamp=TS, from_id=None, summary="s2"),
        ]
    )
    out = apply_updates(items)
    assert [i.id for i in out] == ["b1", "b2"]


# --------------------------------------------------------------------------- #
# derive_state
# --------------------------------------------------------------------------- #


def test_derive_state_model_change_takes_precedence_over_assistant() -> None:
    path: list[SessionEntry] = [
        MessageEntry(
            id="1", parent_id=None, timestamp=TS, item=_assistant_item("a1", model="claude-3")
        ),
        ModelChangeEntry(id="2", parent_id="1", timestamp=TS, provider="openai", model="gpt-4"),
    ]
    state = derive_state(path)
    assert state.model == ("openai", "gpt-4")


def test_derive_state_falls_back_to_latest_assistant_provenance() -> None:
    path: list[SessionEntry] = [
        MessageEntry(
            id="1", parent_id=None, timestamp=TS, item=_assistant_item("a1", model="claude-3")
        ),
        MessageEntry(
            id="2", parent_id="1", timestamp=TS, item=_assistant_item("a2", model="claude-4")
        ),
    ]
    state = derive_state(path)
    assert state.model == ("anthropic", "claude-4")  # latest assistant message


def test_derive_state_no_model_underivable() -> None:
    path: list[SessionEntry] = [
        MessageEntry(id="1", parent_id=None, timestamp=TS, item=_user_item("u1", "a")),
    ]
    state = derive_state(path)
    assert state.model is None


def test_derive_state_thinking_and_tools() -> None:
    path: list[SessionEntry] = [
        ThinkingLevelChangeEntry(id="1", parent_id=None, timestamp=TS, thinking_level="low"),
        ThinkingLevelChangeEntry(id="2", parent_id="1", timestamp=TS, thinking_level="high"),
        ActiveToolsChangeEntry(id="3", parent_id="2", timestamp=TS, active_tool_names=["a"]),
        ActiveToolsChangeEntry(id="4", parent_id="3", timestamp=TS, active_tool_names=["b", "c"]),
    ]
    state = derive_state(path)
    assert state.thinking_level and state.thinking_level.value == "high"
    assert state.active_tool_names == ["b", "c"]


def test_derive_state_model_change_beats_later_assistant_message() -> None:
    # An early ModelChangeEntry still wins over a later assistant message: the
    # fallback applies only when NO model change is on the path.
    path: list[SessionEntry] = [
        ModelChangeEntry(id="1", parent_id=None, timestamp=TS, provider="openai", model="gpt-4"),
        MessageEntry(
            id="2", parent_id="1", timestamp=TS, item=_assistant_item("a1", model="claude-3")
        ),
    ]
    state = derive_state(path)
    assert state.model == ("openai", "gpt-4")


# --------------------------------------------------------------------------- #
# project (composition)
# --------------------------------------------------------------------------- #


def test_project_returns_projection_with_items_only_context() -> None:
    path: list[SessionEntry] = [
        MessageEntry(id="1", parent_id=None, timestamp=TS, item=_user_item("u1", "hi")),
        MessageEntry(id="2", parent_id="1", timestamp=TS, item=_assistant_item("a1")),
    ]
    result = project(path)
    assert isinstance(result, SessionProjection)
    assert result.context.system_prompt is None
    assert result.context.tools is None
    assert [i.id for i in result.context.items] == ["u1", "a1"]
    assert result.state.model == ("anthropic", "claude-3")


def test_project_reprojection_is_stable() -> None:
    path: list[SessionEntry] = [
        MessageEntry(id="1", parent_id=None, timestamp=TS, item=_user_item("u1", "a")),
        MessageUpdateEntry(
            id="2", parent_id="1", timestamp=TS, item=_user_item("u1", "a2"), target_item_id="u1"
        ),
    ]
    first = project(path)
    second = project(path)
    assert first == second
    assert [i.id for i in first.context.items] == ["u1"]
    assert isinstance(first.context.items[0].message, UserMessage)
    assert first.context.items[0].message.content == "a2"


def test_project_full_pipeline_with_compaction_and_tool_result() -> None:
    path: list[SessionEntry] = [
        MessageEntry(id="1", parent_id=None, timestamp=TS, item=_user_item("u1", "old")),
        MessageEntry(id="2", parent_id="1", timestamp=TS, item=_tool_result_item("t1")),
        CompactionEntry(
            id="c",
            parent_id="2",
            timestamp=TS,
            summary="sum",
            first_kept_entry_id=None,
            tokens_before=10,
            retained_tail=[_user_item("u2", "kept")],
        ),
        MessageEntry(id="3", parent_id="c", timestamp=TS, item=_assistant_item("a1")),
    ]
    result = project(path)
    # [summary(c), kept(u2), assistant(a1)] -- u1/t1 dropped by compaction transform
    assert [i.id for i in result.context.items] == ["c", "u2", "a1"]
