from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from otter_ai_core.types import (
    AssistantMessage,
    SessionMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

from .signature import SessionManager

# A SessionManagerFactory yields a fresh, unentered manager. Checks tolerate
# prior history in the bound session and assert only against the messages the
# check itself appended.
type SessionManagerFactory = Callable[[], SessionManager]
type SessionManagerContractCheck = Callable[[SessionManagerFactory], Awaitable[None]]


@contextmanager
def _raises_runtime_error() -> Iterator[None]:
    try:
        yield
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError, none was raised")


@contextmanager
def _propagates(exc_type: type[BaseException]) -> Iterator[None]:
    try:
        yield
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to propagate, it did not")


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


async def check_methods_gated_by_session_lifecycle(make_manager: SessionManagerFactory) -> None:
    manager = make_manager()
    with _raises_runtime_error():
        await manager.append_message(_user_message("hello"))
    with _raises_runtime_error():
        await manager.get_messages()

    async with manager:
        await manager.get_messages()

    with _raises_runtime_error():
        await manager.append_message(_user_message("hello"))
    with _raises_runtime_error():
        await manager.get_messages()


async def check_session_cannot_be_reentered(make_manager: SessionManagerFactory) -> None:
    manager = make_manager()
    async with manager:
        pass
    with _raises_runtime_error():
        await manager.__aenter__()


async def check_exit_does_not_suppress_exceptions(make_manager: SessionManagerFactory) -> None:
    manager = make_manager()
    with _propagates(ZeroDivisionError):
        async with manager:
            await manager.append_message(_user_message("hello"))
            raise ZeroDivisionError


async def check_append_round_trip_fidelity(make_manager: SessionManagerFactory) -> None:
    manager = make_manager()
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


async def check_interleaved_appends_preserve_order_and_snapshots(
    make_manager: SessionManagerFactory,
) -> None:
    manager = make_manager()
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


SESSION_MANAGER_CONTRACT_CHECKS: list[SessionManagerContractCheck] = [
    check_methods_gated_by_session_lifecycle,
    check_session_cannot_be_reentered,
    check_exit_does_not_suppress_exceptions,
    check_append_round_trip_fidelity,
    check_interleaved_appends_preserve_order_and_snapshots,
]
