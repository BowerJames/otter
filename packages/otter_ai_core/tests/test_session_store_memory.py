"""SessionStore contract via the in-memory test store.

Covers append (parent + leaf advance), get/find/entries cursor,
``path_to_root_or_compaction`` stop rules, ``set_leaf_id`` branching,
``stats()`` aggregation (incl. the update-excluded rule), label/session_name,
and the store-level validation backstop (bad parent / bad leaf target).
"""

from __future__ import annotations

import pytest

from otter_ai_core.context import Role, UserContextItem, UserMessage
from otter_ai_core.session_manager import (
    MessageEntry,
    MessageUpdateEntry,
    ModelChangeEntry,
    SessionEntryType,
    SessionError,
    SessionErrorCode,
    SessionMetadata,
    SessionStats,
)
from tests._memory_store import _MemorySessionStore


def _user_item(item_id: str, text: str = "x") -> UserContextItem:
    return UserContextItem(
        id=item_id, message=UserMessage(role=Role.User, content=text, timestamp=1)
    )


@pytest.fixture
def store() -> _MemorySessionStore[SessionMetadata]:
    return _MemorySessionStore(SessionMetadata(id="s1", created_at="2026-01-01T00:00:00Z"))


# --------------------------------------------------------------------------- #
# metadata / leaf / append
# --------------------------------------------------------------------------- #


async def test_metadata_round_trips(store: _MemorySessionStore[SessionMetadata]) -> None:
    md = await store.metadata()
    assert md.id == "s1"


async def test_append_advances_leaf_and_parents(
    store: _MemorySessionStore[SessionMetadata],
) -> None:
    assert await store.leaf_id() is None

    e1 = MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    await store.append_entry(e1)
    assert await store.leaf_id() == "1"

    e2 = MessageEntry(id="2", parent_id="1", timestamp="t", item=_user_item("u2"))
    await store.append_entry(e2)
    assert await store.leaf_id() == "2"


async def test_append_rejects_missing_parent(store: _MemorySessionStore[SessionMetadata]) -> None:
    bad = MessageEntry(id="1", parent_id="ghost", timestamp="t", item=_user_item("u1"))
    with pytest.raises(SessionError) as exc:
        await store.append_entry(bad)
    assert exc.value.code is SessionErrorCode.INVALID_ENTRY


async def test_append_rejects_duplicate_id(store: _MemorySessionStore[SessionMetadata]) -> None:
    await store.append_entry(
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    )
    with pytest.raises(SessionError):
        await store.append_entry(
            MessageEntry(id="1", parent_id="1", timestamp="t", item=_user_item("u2"))
        )


async def test_set_leaf_id_rejects_missing_target(
    store: _MemorySessionStore[SessionMetadata],
) -> None:
    with pytest.raises(SessionError) as exc:
        await store.set_leaf_id("ghost")
    assert exc.value.code is SessionErrorCode.INVALID_ENTRY


async def test_set_leaf_id_to_root_allowed(store: _MemorySessionStore[SessionMetadata]) -> None:
    await store.append_entry(
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    )
    await store.set_leaf_id(None)
    assert await store.leaf_id() is None


# --------------------------------------------------------------------------- #
# get / find / entries cursor
# --------------------------------------------------------------------------- #


async def test_get_entry_hit_and_miss(store: _MemorySessionStore[SessionMetadata]) -> None:
    await store.append_entry(
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    )
    assert (await store.get_entry("1")) is not None
    assert (await store.get_entry("ghost")) is None


async def test_find_entries_narrows_by_type(store: _MemorySessionStore[SessionMetadata]) -> None:
    await store.append_entry(
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    )
    await store.append_entry(
        ModelChangeEntry(id="2", parent_id="1", timestamp="t", provider="anthropic", model="claude")
    )
    messages = await store.find_entries(SessionEntryType.MESSAGE)
    assert len(messages) == 1
    assert all(isinstance(m, MessageEntry) for m in messages)
    assert await store.find_entries(SessionEntryType.MODEL_CHANGE)


async def test_entries_cursor_after_seq_and_limit(
    store: _MemorySessionStore[SessionMetadata],
) -> None:
    for i in range(5):
        parent = None if i == 0 else str(i)
        await store.append_entry(
            MessageEntry(id=str(i + 1), parent_id=parent, timestamp="t", item=_user_item(f"u{i}"))
        )

    first_page = await store.entries(limit=2)
    assert [e.id for e in first_page] == ["1", "2"]

    after = await store.entries(after_seq=2)  # skip first two
    assert [e.id for e in after] == ["3", "4", "5"]


# --------------------------------------------------------------------------- #
# path_to_root_or_compaction
# --------------------------------------------------------------------------- #


async def test_path_to_root_no_compaction(store: _MemorySessionStore[SessionMetadata]) -> None:
    await store.append_entry(
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    )
    await store.append_entry(
        MessageEntry(id="2", parent_id="1", timestamp="t", item=_user_item("u2"))
    )
    await store.append_entry(
        MessageEntry(id="3", parent_id="2", timestamp="t", item=_user_item("u3"))
    )
    path = await store.path_to_root_or_compaction("3")
    assert [e.id for e in path] == ["1", "2", "3"]  # root -> leaf order


async def test_path_to_root_stops_at_retained_tail_compaction(
    store: _MemorySessionStore[SessionMetadata],
) -> None:
    await store.append_entry(
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    )
    await store.append_entry(
        MessageEntry(id="2", parent_id="1", timestamp="t", item=_user_item("u2"))
    )
    from otter_ai_core.session_manager import CompactionEntry

    await store.append_entry(
        CompactionEntry(
            id="c",
            parent_id="2",
            timestamp="t",
            summary="s",
            first_kept_entry_id=None,
            tokens_before=10,
            retained_tail=[_user_item("u2")],
        )
    )
    await store.append_entry(
        MessageEntry(id="3", parent_id="c", timestamp="t", item=_user_item("u3"))
    )
    path = await store.path_to_root_or_compaction("3")
    assert [e.id for e in path] == ["c", "3"]  # stops at the compaction


async def test_path_to_root_keeps_window_for_first_kept(
    store: _MemorySessionStore[SessionMetadata],
) -> None:
    from otter_ai_core.session_manager import CompactionEntry

    await store.append_entry(
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    )
    await store.append_entry(
        MessageEntry(id="2", parent_id="1", timestamp="t", item=_user_item("u2"))
    )
    await store.append_entry(
        MessageEntry(id="3", parent_id="2", timestamp="t", item=_user_item("u3"))
    )
    await store.append_entry(
        CompactionEntry(
            id="c",
            parent_id="3",
            timestamp="t",
            summary="s",
            first_kept_entry_id="2",
            tokens_before=10,
        )
    )
    await store.append_entry(
        MessageEntry(id="4", parent_id="c", timestamp="t", item=_user_item("u4"))
    )
    path = await store.path_to_root_or_compaction("4")
    # stops at first_kept (2): [2, 3, c, 4]
    assert [e.id for e in path] == ["2", "3", "c", "4"]


async def test_path_to_root_none_leaf_is_empty(store: _MemorySessionStore[SessionMetadata]) -> None:
    assert await store.path_to_root_or_compaction(None) == []


# --------------------------------------------------------------------------- #
# label / session_name
# --------------------------------------------------------------------------- #


async def test_label_latest_wins(store: _MemorySessionStore[SessionMetadata]) -> None:
    from otter_ai_core.session_manager import LabelEntry

    await store.append_entry(
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    )
    await store.append_entry(
        LabelEntry(id="l1", parent_id="1", timestamp="t", target_id="u1", label="a")
    )
    assert await store.label("u1") == "a"
    await store.append_entry(
        LabelEntry(id="l2", parent_id="l1", timestamp="t", target_id="u1", label="b")
    )
    assert await store.label("u1") == "b"
    await store.append_entry(
        LabelEntry(id="l3", parent_id="l2", timestamp="t", target_id="u1", label=None)
    )
    assert await store.label("u1") is None  # None clears
    assert await store.label("absent") is None


async def test_session_name_latest_wins(store: _MemorySessionStore[SessionMetadata]) -> None:
    from otter_ai_core.session_manager import SessionInfoEntry

    await store.append_entry(SessionInfoEntry(id="s1", parent_id=None, timestamp="t", name="first"))
    await store.append_entry(
        SessionInfoEntry(id="s2", parent_id="s1", timestamp="t", name="second")
    )
    assert await store.session_name() == "second"


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #


async def test_stats_counts_message_entries_not_updates(
    store: _MemorySessionStore[SessionMetadata],
) -> None:
    await store.append_entry(
        MessageEntry(id="1", parent_id=None, timestamp="t", item=_user_item("u1"))
    )
    await store.append_entry(
        MessageUpdateEntry(
            id="2", parent_id="1", timestamp="t", item=_user_item("u1", "rev"), target_item_id="u1"
        )
    )
    stats = await store.stats()
    assert isinstance(stats, SessionStats)
    assert stats.message_count == 1  # the update does not inflate the count
