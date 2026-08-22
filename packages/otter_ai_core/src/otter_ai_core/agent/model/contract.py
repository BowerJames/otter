from collections.abc import Awaitable, Callable

from otter_ai_core.conversation import TextContent, ToolResultMessage, UserMessage

from .signature import Model

# Checks receive an already-entered model; the test harness owns the
# lifecycle because the agent's Model abstraction doesn't include it.
type AgentModelCheck = Callable[[Model], Awaitable[None]]


async def check_add_user_message_returns_message_with_text(model: Model) -> None:
    message = await model.add_user_message("hello")
    assert isinstance(message, UserMessage)
    assert message.content == [TextContent(text="hello")]


async def check_add_tool_result_message_returns_message_with_text(model: Model) -> None:
    message = await model.add_tool_result_message("tool-call-1", "the result")
    assert isinstance(message, ToolResultMessage)
    assert message.tool_call_id == "tool-call-1"
    assert message.content == [TextContent(text="the result")]


AGENT_MODEL_CONTRACT_CHECKS: list[AgentModelCheck] = [
    check_add_user_message_returns_message_with_text,
    check_add_tool_result_message_returns_message_with_text,
]
