from collections.abc import Callable

import pytest

from ..conversation import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from .signature import SessionManager


def user_message(text: str) -> UserMessage:
    return UserMessage(id=f"user-{text}", content=[TextContent(text=text)])


class SessionManagerConformanceSuite:
    @pytest.fixture
    def make_manager(self) -> Callable[[], SessionManager]:
        # contract: returns a fresh, unentered manager bound to a session with no prior history
        raise NotImplementedError("conformance suite requires a make_manager fixture")

    async def test_methods_rejected_before_enter(
        self, make_manager: Callable[[], SessionManager]
    ) -> None:
        manager = make_manager()
        with pytest.raises(RuntimeError):
            await manager.append_message(user_message("hello"))
        with pytest.raises(RuntimeError):
            await manager.get_messages()

    async def test_methods_rejected_after_exit(
        self, make_manager: Callable[[], SessionManager]
    ) -> None:
        manager = make_manager()
        async with manager:
            await manager.append_message(user_message("hello"))
        with pytest.raises(RuntimeError):
            await manager.append_message(user_message("again"))
        with pytest.raises(RuntimeError):
            await manager.get_messages()

    async def test_reentry_rejected(self, make_manager: Callable[[], SessionManager]) -> None:
        manager = make_manager()
        async with manager:
            await manager.append_message(user_message("hello"))
        with pytest.raises(RuntimeError):
            await manager.__aenter__()

    async def test_exit_does_not_suppress_exceptions(
        self, make_manager: Callable[[], SessionManager]
    ) -> None:
        class Boom(Exception): ...

        manager = make_manager()
        with pytest.raises(Boom):
            async with manager:
                await manager.append_message(user_message("hello"))
                raise Boom()

    async def test_empty_session_returns_empty_sequence(
        self, make_manager: Callable[[], SessionManager]
    ) -> None:
        manager = make_manager()
        async with manager:
            messages = await manager.get_messages()
        assert list(messages) == []

    async def test_append_round_trip_fidelity(
        self, make_manager: Callable[[], SessionManager]
    ) -> None:
        user = user_message("hello")
        assistant = AssistantMessage(
            id="assistant-1",
            content=[ThinkingContent(text="pondering"), TextContent(text="hi there")],
            tool_calls=[
                ToolCall(id="call-1", tool_name="get_weather", parameters={"city": "Leeds"}),
            ],
            stop_reason="tool_call",
        )
        tool_result = ToolResultMessage(
            id="result-1",
            tool_call_id="call-1",
            content=[TextContent(text="18C")],
        )
        manager = make_manager()
        async with manager:
            for message in (user, assistant, tool_result):
                await manager.append_message(message)
            messages = await manager.get_messages()
        assert list(messages) == [user, assistant, tool_result]

    async def test_interleaved_appends_preserve_order(
        self, make_manager: Callable[[], SessionManager]
    ) -> None:
        manager = make_manager()
        async with manager:
            first = user_message("hello")
            await manager.append_message(first)
            assert list(await manager.get_messages()) == [first]

            second = user_message("second")
            await manager.append_message(second)
            assert list(await manager.get_messages()) == [first, second]

            third = user_message("third")
            await manager.append_message(third)
            assert list(await manager.get_messages()) == [first, second, third]
        assert len({m.id for m in (first, second, third)}) == 3

    async def test_get_messages_snapshot_isolation(
        self, make_manager: Callable[[], SessionManager]
    ) -> None:
        manager = make_manager()
        async with manager:
            first = user_message("hello")
            await manager.append_message(first)
            snapshot = await manager.get_messages()

            second = user_message("second")
            await manager.append_message(second)

            assert list(snapshot) == [first]
            assert list(await manager.get_messages()) == [first, second]
        assert len({m.id for m in (first, second)}) == 2
