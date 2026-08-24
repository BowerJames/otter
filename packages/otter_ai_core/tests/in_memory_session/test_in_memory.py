import pytest

from otter_ai_core.in_memory_session import InMemorySessionManager
from otter_ai_core.types import (
    AssistantMessage,
    SessionMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


def _user_message(text: str) -> UserMessage:
    return UserMessage(id=f"user-{text}", content=[TextContent(text=text)])


def _assistant_message() -> AssistantMessage:
    return AssistantMessage(
        id="assistant-1",
        content=[ThinkingContent(text="thinking"), TextContent(text="reply")],
        tool_calls=[ToolCall(id="tool-call-1", tool_name="tool", parameters={})],
        stop_reason="final_response",
    )


def _tool_result_message() -> ToolResultMessage:
    return ToolResultMessage(
        id="tool-result-1",
        tool_call_id="tool-call-1",
        content=[TextContent(text="result")],
    )


async def test_methods_are_gated_by_session_lifecycle() -> None:
    manager = InMemorySessionManager()
    with pytest.raises(RuntimeError):
        await manager.append_message(_user_message("hello"))
    with pytest.raises(RuntimeError):
        await manager.get_messages()

    async with manager:
        await manager.get_messages()

    with pytest.raises(RuntimeError):
        await manager.append_message(_user_message("hello"))
    with pytest.raises(RuntimeError):
        await manager.get_messages()


async def test_entering_an_already_open_session_raises() -> None:
    manager = InMemorySessionManager()
    async with manager:
        with pytest.raises(RuntimeError):
            await manager.__aenter__()


async def test_session_can_be_reopened_after_closing() -> None:
    manager = InMemorySessionManager()
    async with manager:
        await manager.append_message(_user_message("first"))

    async with manager:
        await manager.append_message(_user_message("second"))
        retrieved = await manager.get_messages()

    assert [message.content[0].text for message in retrieved] == ["first", "second"]
    assert [message.content[0].text for message in manager.entries] == ["first", "second"]


async def test_exit_does_not_suppress_exceptions() -> None:
    manager = InMemorySessionManager()
    with pytest.raises(ZeroDivisionError):
        async with manager:
            await manager.append_message(_user_message("hello"))
            raise ZeroDivisionError


async def test_append_round_trip_fidelity() -> None:
    manager = InMemorySessionManager()
    appended: list[SessionMessage] = [
        _user_message("hello"),
        _assistant_message(),
        _tool_result_message(),
    ]
    async with manager:
        for message in appended:
            await manager.append_message(message)
        retrieved = await manager.get_messages()
    assert list(retrieved)[-3:] == appended


async def test_interleaved_appends_preserve_order_and_snapshots() -> None:
    manager = InMemorySessionManager()
    first = _user_message("first")
    second = _user_message("second")
    third = _user_message("third")
    async with manager:
        await manager.append_message(first)
        held = await manager.get_messages()
        await manager.append_message(second)
        after_two = await manager.get_messages()
        await manager.append_message(third)
        after_three = await manager.get_messages()
    assert list(held) == list(after_two)[:-1]
    assert list(after_two)[-2:] == [first, second]
    assert list(after_three)[-3:] == [first, second, third]


async def test_entries_reflects_appended_messages_across_session_lifecycle() -> None:
    manager = InMemorySessionManager()
    initial = manager.entries
    assert initial == ()
    first = _user_message("first")
    second = _user_message("second")
    async with manager:
        await manager.append_message(first)
        held = manager.entries
        assert held == (first,)
        await manager.append_message(second)
    assert held == (first,)
    assert list(manager.entries) == [first, second]
