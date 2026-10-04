"""Behaviour of OpenAIChatCompletionsCompatibleConversation, observed at a fake endpoint."""

import json
from json import JSONDecodeError
from typing import Any

import httpx2
import pytest
from openai import APIStatusError, AsyncOpenAI

from otter.messages import (
    AssistantMessage,
    AudioPart,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    UserPart,
)
from otter.openai_chat_completions_compatible import OpenAIChatCompletionsCompatibleConversation


def text_reply(text: str) -> dict[str, Any]:
    """The wire form of an assistant turn that only says `text`."""
    return {"role": "assistant", "content": text}


def tool_call_reply(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    """The wire form of an assistant turn asking for one tool call; `arguments` is JSON text."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}
        ],
    }


class FakeChatCompletionsEndpoint:
    """A test adapter for the network: records each request body, answers with scripted turns.

    Each request is answered with the next entry of `replies`; once they run out, with a
    plain text turn. Setting `fail_next` makes the next request fail with a server error.
    """

    def __init__(self) -> None:
        self.request_bodies: list[Any] = []
        self.replies: list[dict[str, Any]] = []
        self.fail_next = False

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.request_bodies.append(json.loads(request.content))
        if self.fail_next:
            self.fail_next = False
            return httpx2.Response(500, json={"error": {"message": "server error"}})
        message = self.replies.pop(0) if self.replies else text_reply("OK")
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "glm-4.6",
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            },
        )


READ_FILE = ToolSpec(
    name="read_file",
    description="Read a file from disk.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)


@pytest.fixture
def fake_endpoint() -> FakeChatCompletionsEndpoint:
    return FakeChatCompletionsEndpoint()


@pytest.fixture
def client(fake_endpoint: FakeChatCompletionsEndpoint) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://provider.test/v1",
        api_key="test-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(fake_endpoint)),
    )


async def test_generating_sends_the_added_user_message_to_the_configured_model(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(client, model="glm-4.6")
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    assert fake_endpoint.request_bodies == [
        {
            "model": "glm-4.6",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}],
        }
    ]


async def test_generating_returns_the_text_the_model_replied_with(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [text_reply("Hi there")]
    conversation = OpenAIChatCompletionsCompatibleConversation(client, model="glm-4.6")
    conversation.add_user_message([TextPart("Hello")])

    reply = await conversation.generate()

    assert reply == AssistantMessage(content=(TextPart("Hi there"),))


async def test_generating_again_sends_the_earlier_turns_before_the_new_one(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [text_reply("Hi there")]
    conversation = OpenAIChatCompletionsCompatibleConversation(client, model="glm-4.6")
    conversation.add_user_message([TextPart("Hello")])
    await conversation.generate()
    conversation.add_user_message([TextPart("How are you?")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[1]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": [{"type": "text", "text": "How are you?"}]},
    ]


async def test_generating_sends_the_system_prompt_ahead_of_the_conversation(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client, model="glm-4.6", system="You are terse."
    )
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"] == [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
    ]


async def test_generating_offers_the_model_the_conversations_tools(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client, model="glm-4.6", tools=[READ_FILE]
    )
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from disk.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]


async def test_generating_returns_the_tool_call_the_model_asked_for(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [tool_call_reply("call_1", "read_file", '{"path": "notes.txt"}')]
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client, model="glm-4.6", tools=[READ_FILE]
    )
    conversation.add_user_message([TextPart("What is in my notes?")])

    reply = await conversation.generate()

    assert reply == AssistantMessage(
        content=(ToolCall(id="call_1", name="read_file", arguments={"path": "notes.txt"}),)
    )


async def test_generating_after_a_tool_result_sends_the_call_and_its_result(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [tool_call_reply("call_1", "read_file", '{"path": "notes.txt"}')]
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client, model="glm-4.6", tools=[READ_FILE]
    )
    conversation.add_user_message([TextPart("What is in my notes?")])
    await conversation.generate()
    conversation.add_tool_result("call_1", "buy milk")

    await conversation.generate()

    assert fake_endpoint.request_bodies[1]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "What is in my notes?"}]},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "notes.txt"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "buy milk"},
    ]


async def test_generating_again_after_a_failed_request_resends_the_same_conversation(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(client, model="glm-4.6")
    conversation.add_user_message([TextPart("Hello")])
    fake_endpoint.fail_next = True
    with pytest.raises(APIStatusError):
        await conversation.generate()

    await conversation.generate()

    assert fake_endpoint.request_bodies[1]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
    ]


async def test_generating_again_after_unreadable_tool_arguments_resends_the_same_conversation(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [tool_call_reply("call_1", "read_file", '{"path": ')]
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client, model="glm-4.6", tools=[READ_FILE]
    )
    conversation.add_user_message([TextPart("What is in my notes?")])
    with pytest.raises(JSONDecodeError):
        await conversation.generate()

    await conversation.generate()

    assert fake_endpoint.request_bodies[1]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "What is in my notes?"}]}
    ]


async def test_generating_sends_an_inline_image_as_a_data_uri_in_its_place_among_the_text(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(client, model="glm-4.6")
    conversation.add_user_message(
        [
            TextPart("Before"),
            ImagePart(data="iVBORw==", media_type="image/png"),
            TextPart("After"),
        ]
    )

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"][0]["content"] == [
        {"type": "text", "text": "Before"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw=="}},
        {"type": "text", "text": "After"},
    ]


async def test_generating_sends_inline_audio_with_its_format(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(client, model="glm-4.6")
    conversation.add_user_message([AudioPart(data="UklGRg==", format="wav")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"][0]["content"] == [
        {"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "wav"}}
    ]


async def test_generating_sends_an_image_url_for_the_provider_to_fetch(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(client, model="glm-4.6")
    conversation.add_user_message([ImageUrlPart(url="https://images.test/cat.png")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"][0]["content"] == [
        {"type": "image_url", "image_url": {"url": "https://images.test/cat.png"}}
    ]


async def test_generating_returns_the_models_thinking_ahead_of_its_text(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [
        {"role": "assistant", "content": "pong", "reasoning_content": "They want pong."}
    ]
    conversation = OpenAIChatCompletionsCompatibleConversation(client, model="glm-4.6")
    conversation.add_user_message([TextPart("ping")])

    reply = await conversation.generate()

    assert reply == AssistantMessage(content=(ThinkingPart("They want pong."), TextPart("pong")))


@pytest.mark.parametrize(
    "image",
    [
        ImagePart(data="iVBORw==", media_type="image/png"),
        ImageUrlPart(url="https://images.test/cat.png"),
    ],
)
async def test_generating_for_a_model_without_image_support_sends_a_note_in_place_of_an_image(
    image: UserPart, fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client, model="glm-4.6", supports_images=False
    )
    conversation.add_user_message([TextPart("Before"), image, TextPart("After")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"][0]["content"] == [
        {"type": "text", "text": "Before"},
        {"type": "text", "text": "[image omitted: this model cannot view images]"},
        {"type": "text", "text": "After"},
    ]


async def test_generating_for_a_model_without_audio_support_sends_a_note_in_place_of_audio(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client, model="glm-4.6", supports_audio=False
    )
    conversation.add_user_message([AudioPart(data="UklGRg==", format="wav")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"][0]["content"] == [
        {"type": "text", "text": "[audio omitted: this model cannot hear audio]"}
    ]


async def test_generating_sends_the_context_a_conversation_starts_with_ahead_of_what_is_added(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client,
        model="glm-4.6",
        system="You are terse.",
        context=[
            UserMessage((TextPart("What is in my notes?"),)),
            AssistantMessage(
                (
                    TextPart("Let me look."),
                    ToolCall(id="call_1", name="read_file", arguments={"path": "notes.txt"}),
                )
            ),
            ToolResultMessage("call_1", "Buy milk."),
            AssistantMessage((TextPart("They say to buy milk."),)),
        ],
    )
    conversation.add_user_message([TextPart("Thanks")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"] == [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": [{"type": "text", "text": "What is in my notes?"}]},
        {
            "role": "assistant",
            "content": "Let me look.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "notes.txt"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "Buy milk."},
        {"role": "assistant", "content": "They say to buy milk."},
        {"role": "user", "content": [{"type": "text", "text": "Thanks"}]},
    ]


async def test_generating_sends_an_assistant_turn_of_the_context_without_its_thinking(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client,
        model="glm-4.6",
        context=[
            UserMessage((TextPart("Hello"),)),
            AssistantMessage((ThinkingPart("A greeting; greet back."), TextPart("Hi there"))),
        ],
    )

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"][1] == {
        "role": "assistant",
        "content": "Hi there",
    }


async def test_generating_sends_a_tool_call_only_turn_of_the_context_without_content(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client,
        model="glm-4.6",
        context=[
            AssistantMessage((ToolCall(id="call_1", name="read_file", arguments={}),)),
        ],
    )

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"] == [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        }
    ]


async def test_generating_sends_a_note_in_place_of_an_image_of_the_context_the_model_cannot_view(
    fake_endpoint: FakeChatCompletionsEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIChatCompletionsCompatibleConversation(
        client,
        model="glm-4.6",
        supports_images=False,
        context=[UserMessage((ImageUrlPart(url="https://example.test/cat.png"),))],
    )

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["messages"][0]["content"] == [
        {"type": "text", "text": "[image omitted: this model cannot view images]"}
    ]
