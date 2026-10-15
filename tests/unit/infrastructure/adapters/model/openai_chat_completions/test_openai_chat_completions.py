"""Behaviour of the chat completions adapter, driven through the model's port and observed at a
fake endpoint.
"""

from json import JSONDecodeError

import pytest

from otter.core.domain.messages import (
    AssistantMessage,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
)
from otter.core.model import ModelInput, ModelPort
from otter.infrastructure.adapters.model.openai_chat_completions import (
    OpenAIChatCompletionsAdapter,
)

from .adapters import FakeChatCompletionsEndpoint, text_reply, tool_call_reply

READ_FILE = ToolSpec(
    name="read_file",
    description="Read a file from disk.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
)
HELLO = UserMessage((TextPart("Hello"),))


def asking(*context: ContextEntry, system: str | None = None) -> ModelInput:
    return ModelInput(system, (), context)


@pytest.fixture
def endpoint() -> FakeChatCompletionsEndpoint:
    return FakeChatCompletionsEndpoint()


@pytest.fixture
def adapter(endpoint: FakeChatCompletionsEndpoint) -> ModelPort:
    return OpenAIChatCompletionsAdapter(endpoint.client(), "glm-4.6")


async def test_the_context_is_sent_to_the_model_it_was_made_for(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(asking(HELLO))

    assert endpoint.request_bodies == [
        {
            "model": "glm-4.6",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}],
        }
    ]


async def test_the_system_prompt_is_sent_ahead_of_the_context(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(asking(HELLO, system="Be brief."))

    assert endpoint.request_bodies[0]["messages"][0] == {"role": "system", "content": "Be brief."}


async def test_the_tools_are_offered_as_functions(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(ModelInput(None, (READ_FILE,), (HELLO,)))

    assert endpoint.request_bodies[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from disk.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }
    ]


async def test_the_turn_is_the_text_the_model_replied_with(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [text_reply("Hi there")]

    assert await adapter.generate(asking(HELLO)) == AssistantMessage((TextPart("Hi there"),))


async def test_the_turn_holds_the_tool_call_the_model_asked_for(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [tool_call_reply("call-1", "read_file", '{"path": "a.txt"}')]

    assert await adapter.generate(asking(HELLO)) == AssistantMessage(
        (ToolCall("call-1", "read_file", {"path": "a.txt"}),)
    )


async def test_the_turn_holds_the_models_thinking_ahead_of_its_text(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [{**text_reply("Four."), "reasoning_content": "Two and two."}]

    assert await adapter.generate(asking(HELLO)) == AssistantMessage(
        (ThinkingPart("Two and two."), TextPart("Four."))
    )


async def test_tool_arguments_that_are_not_json_raise(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    endpoint.replies = [tool_call_reply("call-1", "read_file", "{not json")]

    with pytest.raises(JSONDecodeError):
        await adapter.generate(asking(HELLO))


async def test_the_parts_of_a_user_turn_are_sent_in_order(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(
        asking(
            UserMessage(
                (
                    TextPart("Look"),
                    ImagePart(data="iVBORw==", media_type="image/png"),
                    ImageUrlPart(url="https://example.test/cat.png"),
                    AudioPart(data="UklGRg==", format="wav"),
                )
            )
        )
    )

    assert endpoint.request_bodies[0]["messages"][0]["content"] == [
        {"type": "text", "text": "Look"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw=="}},
        {"type": "image_url", "image_url": {"url": "https://example.test/cat.png"}},
        {"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "wav"}},
    ]


async def test_an_assistant_turn_is_sent_as_its_text_and_tool_calls_without_its_thinking(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(
        asking(
            HELLO,
            AssistantMessage(
                (
                    ThinkingPart("The file will say."),
                    TextPart("Let me look."),
                    TextPart("One moment."),
                    ToolCall("call-1", "read_file", {"path": "a.txt"}),
                )
            ),
            ToolResultMessage("call-1", "file contents"),
        )
    )

    assert endpoint.request_bodies[0]["messages"][1:] == [
        {
            "role": "assistant",
            "content": "Let me look.\n\nOne moment.",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "file contents"},
    ]


async def test_an_assistant_turn_of_tool_calls_alone_is_sent_without_content(
    endpoint: FakeChatCompletionsEndpoint, adapter: ModelPort
) -> None:
    await adapter.generate(
        asking(HELLO, AssistantMessage((ToolCall("call-1", "read_file", {"path": "a.txt"}),)))
    )

    assert "content" not in endpoint.request_bodies[0]["messages"][1]


async def test_opening_and_closing_leave_the_client_able_to_generate(
    endpoint: FakeChatCompletionsEndpoint,
) -> None:
    client = endpoint.client()
    first = OpenAIChatCompletionsAdapter(client, "glm-4.6")
    await first.open()
    await first.close()

    await OpenAIChatCompletionsAdapter(client, "glm-4.6").generate(asking(HELLO))

    assert len(endpoint.request_bodies) == 1
