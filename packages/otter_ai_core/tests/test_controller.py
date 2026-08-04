"""SessionStoreController: append/update/project/branch/compact + observability.

Stands up a real :class:`tests._memory_store._MemorySessionStore` (test infra)
under the controller. Exercises writes + the lock, projection round-trip,
branch divergence, event publication (ENTRY_APPENDED + refined), validation,
the orphan-update rule, and teardown.
"""

from __future__ import annotations

import asyncio

import pytest

from otter_ai_core import (
    AssistantContextItem,
    AssistantMessage,
    StopReason,
    TextContent,
    ThinkingLevel,
    Usage,
    UsageCost,
)
from otter_ai_core.data_models.context import Role, UserContextItem, UserMessage
from otter_ai_core.data_models.events import (
    COMPACTED,
    ENTRY_APPENDED,
    ITEM_ADDED,
    ITEM_UPDATED,
    TREE_CHANGED,
    SessionStoreControllerEventTypes,
)
from otter_ai_core.data_models.session import (
    BranchSummaryInput,
    SessionError,
    SessionErrorCode,
    SessionMetadata,
    SessionProjection,
)
from otter_ai_core.runtime.session import SessionStoreController
from tests._memory_store import _MemorySessionStore


def _zero_cost() -> UsageCost:
    return UsageCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0, total=0.0)


def _user_item(item_id: str, text: str = "x") -> UserContextItem:
    return UserContextItem(
        id=item_id, message=UserMessage(role=Role.User, content=text, timestamp=1)
    )


def _assistant_item(item_id: str, model: str = "claude-3") -> AssistantContextItem:
    return AssistantContextItem(
        id=item_id,
        message=AssistantMessage(
            role=Role.Assistant,
            content=[TextContent(type="text", text="ok")],
            api="anthropic-messages",
            provider="anthropic",
            model=model,
            usage=Usage(
                input=1, output=1, cache_read=0, cache_write=0, total_tokens=2, cost=_zero_cost()
            ),
            stop_reason=StopReason.Stop,
            timestamp=2,
        ),
    )


def _new_controller() -> SessionStoreController[SessionMetadata]:
    store = _MemorySessionStore(SessionMetadata(id="s1", created_at="2026-01-01T00:00:00Z"))
    return SessionStoreController(store)


# --------------------------------------------------------------------------- #
# Append + projection round-trip
# --------------------------------------------------------------------------- #


async def test_append_returns_tree_id_and_advances_leaf() -> None:
    async with _new_controller() as c:
        assert await c.leaf_id() is None
        tree_id = await c.append_message(_user_item("u1", "hi"))
        assert tree_id  # opaque, non-empty
        assert await c.leaf_id() == tree_id


async def test_projection_round_trips_appended_items() -> None:
    async with _new_controller() as c:
        await c.append_message(_user_item("u1", "hi"))
        await c.append_message(_user_item("u2", "bye"))
        result = await c.projection()
        assert isinstance(result, SessionProjection)
        assert [i.id for i in result.context.items] == ["u1", "u2"]
        assert result.context.system_prompt is None
        assert result.context.tools is None


async def test_build_context_items_only() -> None:
    async with _new_controller() as c:
        await c.append_message(_user_item("u1", "hi"))
        ctx = await c.build_context()
        assert [i.id for i in ctx.items] == ["u1"]


# --------------------------------------------------------------------------- #
# update_message (append-only amendment)
# --------------------------------------------------------------------------- #


async def test_update_message_amends_in_place() -> None:
    async with _new_controller() as c:
        await c.append_message(_user_item("u1", "orig"))
        await c.update_message(_user_item("u1", "revised"))
        ctx = await c.build_context()
        assert [i.id for i in ctx.items] == ["u1"]  # not duplicated
        msg = ctx.items[0].message
        assert isinstance(msg, UserMessage)
        assert msg.content == "revised"


async def test_update_message_orphan_is_harmless() -> None:
    async with _new_controller() as c:
        await c.append_message(_user_item("u1", "a"))
        await c.update_message(_user_item("u99", "orphan"))  # u99 never added
        ctx = await c.build_context()
        assert {i.id for i in ctx.items} == {"u1", "u99"}


async def test_update_message_generalizes_to_assistant_role() -> None:
    async with _new_controller() as c:
        await c.append_message(_assistant_item("a1", "claude-3"))
        await c.update_message(_assistant_item("a1", "claude-4"))
        ctx = await c.build_context()
        assert [i.id for i in ctx.items] == ["a1"]
        item = ctx.items[0]
        assert isinstance(item.message, AssistantMessage)
        assert item.message.model == "claude-4"


# --------------------------------------------------------------------------- #
# Change entries -> derive_state
# --------------------------------------------------------------------------- #


async def test_append_model_change_appears_in_state() -> None:
    async with _new_controller() as c:
        await c.append_model_change("openai", "gpt-4")
        state = (await c.projection()).state
        assert state.model == ("openai", "gpt-4")


async def test_append_thinking_and_tools_change() -> None:
    async with _new_controller() as c:
        await c.append_thinking_level_change(ThinkingLevel.High)
        await c.append_active_tools_change(["search", "calc"])
        state = (await c.projection()).state
        assert state.thinking_level is ThinkingLevel.High
        assert state.active_tool_names == ["search", "calc"]


# --------------------------------------------------------------------------- #
# Compaction
# --------------------------------------------------------------------------- #


async def test_append_compaction_collapses_projection() -> None:
    async with _new_controller() as c:
        await c.append_message(_user_item("u1", "old1"))
        await c.append_message(_user_item("u2", "old2"))
        await c.append_compaction(
            summary="sum",
            first_kept_entry_id=None,
            tokens_before=10,
            retained_tail=[_user_item("u2", "old2")],
        )
        await c.append_message(_user_item("u3", "new"))
        ctx = await c.build_context()
        # [summary, retained u2, u3] -- u1 dropped by the compaction
        ids = [i.id for i in ctx.items]
        assert ids[0] != "u2"  # the synthesized summary item (tree id)
        assert ids[1:] == ["u2", "u3"]


# --------------------------------------------------------------------------- #
# custom / label / session name
# --------------------------------------------------------------------------- #


async def test_append_custom_message_projected_label_and_session_name() -> None:
    async with _new_controller() as c:
        tree = await c.append_message(_user_item("u1", "hi"))
        await c.append_custom_message("note", "a note", display=True)
        # custom (non-projected) state does not appear in context
        await c.append_custom("kv", {"k": 1})
        ctx = await c.build_context()
        assert len(ctx.items) == 2  # u1 + the custom message
        # label
        await c.append_label(tree, "pinned")
        assert await c.store.label(tree) == "pinned"
        # session name (sanitized)
        await c.append_session_name("my\r\nname")
        assert await c.store.session_name() == "my name"


async def test_append_label_missing_target_raises() -> None:
    async with _new_controller() as c:
        with pytest.raises(SessionError) as exc:
            await c.append_label("ghost", "x")
        assert exc.value.code is SessionErrorCode.INVALID_ENTRY


# --------------------------------------------------------------------------- #
# Branching
# --------------------------------------------------------------------------- #


async def test_move_to_diverges_history() -> None:
    async with _new_controller() as c:
        await c.append_message(_user_item("u1"))
        branch_point = await c.append_message(_user_item("u2"))
        await c.append_message(_user_item("u3"))  # on the trunk
        await c.move_to(branch_point)  # rewind to u2
        await c.append_message(_user_item("u4"))  # diverges
        ctx = await c.build_context()
        assert [i.id for i in ctx.items] == ["u1", "u2", "u4"]  # u3 branched away


async def test_move_to_missing_target_raises() -> None:
    async with _new_controller() as c:
        with pytest.raises(SessionError) as exc:
            await c.move_to("ghost")
        assert exc.value.code is SessionErrorCode.INVALID_ENTRY


async def test_move_to_to_root() -> None:
    async with _new_controller() as c:
        await c.append_message(_user_item("u1"))
        await c.append_message(_user_item("u2"))
        await c.move_to(None)  # back to root
        assert await c.leaf_id() is None
        await c.append_message(_user_item("u3"))
        ctx = await c.build_context()
        assert [i.id for i in ctx.items] == ["u3"]  # only the post-root append


async def test_move_to_with_summary_records_branch_summary() -> None:
    async with _new_controller() as c:
        await c.append_message(_user_item("u1"))
        target = await c.append_message(_user_item("u2"))
        summary_id = await c.move_to(target, summary=BranchSummaryInput(summary="forked here"))
        assert summary_id is not None
        # the summary entry is on the new branch and projected as a marker
        ctx = await c.build_context()
        ids = [i.id for i in ctx.items]
        assert summary_id in ids  # synthesized marker item uses the tree id


# --------------------------------------------------------------------------- #
# Observability (Bus)
# --------------------------------------------------------------------------- #


async def _collect(
    controller: SessionStoreController[SessionMetadata],
    event: object,
) -> tuple[list[object], asyncio.Event]:
    seen: list[object] = []
    fired = asyncio.Event()

    async def handler(payload: object) -> None:
        seen.append(payload)
        fired.set()

    controller.on(event, handler)  # type: ignore[arg-type]
    return seen, fired


async def test_entry_appended_fires_for_every_append() -> None:
    async with _new_controller() as c:
        seen, fired = await _collect(c, ENTRY_APPENDED)
        await c.append_message(_user_item("u1"))
        await asyncio.wait_for(fired.wait(), timeout=1.0)
        assert len(seen) == 1


async def test_item_added_and_item_updated_refined_events() -> None:
    async with _new_controller() as c:
        added: list[object] = []
        updated: list[object] = []
        added_fired = asyncio.Event()
        updated_fired = asyncio.Event()

        async def on_added(payload: object) -> None:
            added.append(payload)
            added_fired.set()

        async def on_updated(payload: object) -> None:
            updated.append(payload)
            updated_fired.set()

        c.on(ITEM_ADDED, on_added)
        c.on(ITEM_UPDATED, on_updated)
        await c.append_message(_user_item("u1"))
        await asyncio.wait_for(added_fired.wait(), timeout=1.0)
        await c.update_message(_user_item("u1", "v2"))
        await asyncio.wait_for(updated_fired.wait(), timeout=1.0)
        assert len(added) == 1
        assert len(updated) == 1


async def test_compacted_event_fires() -> None:
    async with _new_controller() as c:
        seen, fired = await _collect(c, COMPACTED)
        await c.append_compaction(summary="s", first_kept_entry_id=None, tokens_before=1)
        await asyncio.wait_for(fired.wait(), timeout=1.0)
        assert len(seen) == 1


async def test_tree_changed_event_payload() -> None:
    async with _new_controller() as c:
        await c.append_message(_user_item("u1"))
        target = await c.append_message(_user_item("u2"))
        seen: list[object] = []
        fired = asyncio.Event()

        async def on_tree(payload: object) -> None:
            seen.append(payload)
            fired.set()

        c.on(TREE_CHANGED, on_tree)
        await c.move_to(target)
        await asyncio.wait_for(fired.wait(), timeout=1.0)
        assert len(seen) == 1


async def test_event_type_enum_values() -> None:
    assert SessionStoreControllerEventTypes.ENTRY_APPENDED.value == "session.entry_appended"
    assert SessionStoreControllerEventTypes.TREE_CHANGED.value == "session.tree_changed"


# --------------------------------------------------------------------------- #
# Concurrency (the lock serializes appends)
# --------------------------------------------------------------------------- #


async def test_concurrent_appends_serialize_into_a_single_chain() -> None:
    async with _new_controller() as c:
        ids = await asyncio.gather(*(c.append_message(_user_item(f"u{i}")) for i in range(6)))
        assert len(set(ids)) == 6  # distinct tree ids
        # A non-linear (stale-leaf) race would fork the tree, so the path from
        # the final leaf would contain fewer than 6 entries.
        path = await c.get_branch()
        assert len(path) == 6
        ctx = await c.build_context()
        assert {i.id for i in ctx.items} == {f"u{i}" for i in range(6)}


# --------------------------------------------------------------------------- #
# Restorability
# --------------------------------------------------------------------------- #


async def test_rebuild_over_same_store_yields_identical_projection() -> None:
    store = _MemorySessionStore(SessionMetadata(id="s1", created_at="2026-01-01T00:00:00Z"))
    async with SessionStoreController(store) as c:
        await c.append_message(_user_item("u1", "a"))
        await c.append_message(_user_item("u2", "b"))
        first = await c.projection()
    # A fresh controller over the SAME populated store rebuilds identically.
    async with SessionStoreController(store) as c2:
        second = await c2.projection()
    assert second == first
