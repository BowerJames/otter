"""Behaviour of InMemorySessionManager, observed through the entries it returns."""

from otter.in_memory_session_manager import InMemorySessionManager
from otter.messages import (
    AssistantMessage,
    ContextEntry,
    TextPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

ASKS = UserMessage((TextPart("What is in a.txt?"),))
CALLS = AssistantMessage((ToolCall("call-1", "read_file", {"path": "a.txt"}),))
RESULT = ToolResultMessage("call-1", "file contents")


def test_a_new_session_manager_holds_no_entries() -> None:
    assert list(InMemorySessionManager().entries()) == []


def test_appended_entries_are_returned_in_the_order_they_were_appended() -> None:
    manager = InMemorySessionManager()
    manager.append(ASKS)
    manager.append(CALLS)
    manager.append(RESULT)

    assert list(manager.entries()) == [ASKS, CALLS, RESULT]


def test_a_session_manager_starts_out_holding_the_entries_it_is_given() -> None:
    manager = InMemorySessionManager([ASKS, CALLS])
    manager.append(RESULT)

    assert list(manager.entries()) == [ASKS, CALLS, RESULT]


def test_entries_already_returned_are_unchanged_by_a_later_append() -> None:
    manager = InMemorySessionManager()
    manager.append(ASKS)
    returned = manager.entries()

    manager.append(CALLS)

    assert list(returned) == [ASKS]


def test_changing_the_entries_it_was_given_does_not_change_what_it_holds() -> None:
    given: list[ContextEntry] = [ASKS]
    manager = InMemorySessionManager(given)

    given.append(CALLS)

    assert list(manager.entries()) == [ASKS]
