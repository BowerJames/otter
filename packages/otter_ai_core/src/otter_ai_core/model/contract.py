from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from otter_ai_core.agent_tool import AgentTool
from otter_ai_core.conversation import TextContent, ToolResultMessage, UserMessage

from .signature import Model

# A ModelFactory yields a fresh, unentered model, bound to the given system
# prompt and tools, whose session can complete at least one generate() and
# accepts a tool result for an arbitrary tool_call_id. Anything a check needs
# to observe through the interface must be arranged by the factory; checks
# receive nothing else.
type ModelFactory = Callable[[str, list[AgentTool]], Model]
type ModelContractCheck = Callable[[ModelFactory], Awaitable[None]]


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


async def check_methods_gated_by_session_lifecycle(make_model: ModelFactory) -> None:
    model = make_model("system prompt", [])
    with _raises_runtime_error():
        await model.add_user_message("hello")
    with _raises_runtime_error():
        await model.add_tool_result_message("tool-call-1", "result")
    with _raises_runtime_error():
        await model.generate()

    async with model:
        await model.add_user_message("hello")
        await model.add_tool_result_message("tool-call-1", "result")
        await model.generate()

    with _raises_runtime_error():
        await model.add_user_message("hello")
    with _raises_runtime_error():
        await model.add_tool_result_message("tool-call-1", "result")
    with _raises_runtime_error():
        await model.generate()


async def check_session_cannot_be_reentered(make_model: ModelFactory) -> None:
    model = make_model("system prompt", [])
    async with model:
        pass
    with _raises_runtime_error():
        await model.__aenter__()


async def check_exit_does_not_suppress_exceptions(make_model: ModelFactory) -> None:
    model = make_model("system prompt", [])
    with _propagates(ZeroDivisionError):
        async with model:
            await model.add_user_message("hello")
            raise ZeroDivisionError


async def check_add_user_message_returns_message_with_text(make_model: ModelFactory) -> None:
    model = make_model("system prompt", [])
    async with model:
        message = await model.add_user_message("hello")
    assert isinstance(message, UserMessage)
    assert message.content == [TextContent(text="hello")]


async def check_add_tool_result_message_returns_message_with_text(
    make_model: ModelFactory,
) -> None:
    model = make_model("system prompt", [])
    async with model:
        message = await model.add_tool_result_message("tool-call-1", "the result")
    assert isinstance(message, ToolResultMessage)
    assert message.tool_call_id == "tool-call-1"
    assert message.content == [TextContent(text="the result")]


MODEL_CONTRACT_CHECKS: list[ModelContractCheck] = [
    check_methods_gated_by_session_lifecycle,
    check_session_cannot_be_reentered,
    check_exit_does_not_suppress_exceptions,
    check_add_user_message_returns_message_with_text,
    check_add_tool_result_message_returns_message_with_text,
]
