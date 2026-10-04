"""Behaviour of OpenAIResponsesCompatibleConversation, observed at a fake endpoint."""

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
    ToolSpec,
    UserPart,
)
from otter.openai_responses_compatible import OpenAIResponsesCompatibleConversation


def text_item(text: str) -> dict[str, Any]:
    """The wire form of an output item in which the model says `text`."""
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def tool_call_item(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    """The wire form of an output item asking for one tool call; `arguments` is JSON text."""
    return {
        "id": f"fc_{call_id}",
        "type": "function_call",
        "status": "completed",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }


def reasoning_item(**shown: Any) -> dict[str, Any]:
    """The wire form of an output item holding the model's reasoning, shown as `shown`."""
    return {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [],
        "encrypted_content": "gAAAAB-opaque",
        **shown,
    }


class FakeResponsesEndpoint:
    """A test adapter for the network: records each request body, answers with scripted turns.

    Each request is answered with the next entry of `replies`, the output items of one
    turn; once they run out, with a plain text turn. Setting `fail_next` makes the next
    request fail with a server error; setting `error_next` makes the next response
    report that the model failed.
    """

    def __init__(self) -> None:
        self.request_bodies: list[Any] = []
        self.replies: list[list[dict[str, Any]]] = []
        self.fail_next = False
        self.error_next: dict[str, Any] | None = None

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.request_bodies.append(json.loads(request.content))
        if self.fail_next:
            self.fail_next = False
            return httpx2.Response(500, json={"error": {"message": "server error"}})
        if self.error_next:
            error, self.error_next = self.error_next, None
            return httpx2.Response(200, json=self._response("failed", error, []))
        output = self.replies.pop(0) if self.replies else [text_item("OK")]
        return httpx2.Response(200, json=self._response("completed", None, output))

    def _response(
        self, status: str, error: dict[str, Any] | None, output: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "id": "resp_1",
            "object": "response",
            "created_at": 0,
            "model": "gpt-5.1",
            "status": status,
            "error": error,
            "output": output,
        }


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
def fake_endpoint() -> FakeResponsesEndpoint:
    return FakeResponsesEndpoint()


@pytest.fixture
def client(fake_endpoint: FakeResponsesEndpoint) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://provider.test/v1",
        api_key="test-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(fake_endpoint)),
    )


async def test_generating_sends_the_added_user_message_to_the_configured_model(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    [body] = fake_endpoint.request_bodies
    assert body["model"] == "gpt-5.1"
    assert body["input"] == [{"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}]


async def test_generating_returns_the_text_the_model_replied_with(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [[text_item("Hi there")]]
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])

    reply = await conversation.generate()

    assert reply == AssistantMessage(content=(TextPart("Hi there"),))


async def test_generating_again_sends_the_earlier_turns_before_the_new_one(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [[text_item("Hi there")]]
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])
    await conversation.generate()
    conversation.add_user_message([TextPart("How are you?")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[1]["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "Hi there", "annotations": []}],
        },
        {"role": "user", "content": [{"type": "input_text", "text": "How are you?"}]},
    ]


async def test_generating_sends_the_system_prompt_as_the_models_instructions(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(
        client, model="gpt-5.1", system="You are terse."
    )
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["instructions"] == "You are terse."


async def test_generating_without_a_system_prompt_sends_no_instructions(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    assert "instructions" not in fake_endpoint.request_bodies[0]


async def test_generating_asks_the_provider_not_to_keep_the_conversation(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["store"] is False


async def test_generating_asks_for_reasoning_in_the_form_that_can_be_sent_back(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["include"] == ["reasoning.encrypted_content"]


async def test_generating_offers_the_model_the_conversations_tools(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1", tools=[READ_FILE])
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file from disk.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "strict": False,
        }
    ]


async def test_generating_returns_the_tool_call_the_model_asked_for(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [[tool_call_item("call_1", "read_file", '{"path": "notes.txt"}')]]
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1", tools=[READ_FILE])
    conversation.add_user_message([TextPart("What is in my notes?")])

    reply = await conversation.generate()

    assert reply == AssistantMessage(
        content=(ToolCall(id="call_1", name="read_file", arguments={"path": "notes.txt"}),)
    )


async def test_generating_after_a_tool_result_sends_the_models_turn_and_the_result(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [
        [reasoning_item(), tool_call_item("call_1", "read_file", '{"path": "notes.txt"}')]
    ]
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1", tools=[READ_FILE])
    conversation.add_user_message([TextPart("What is in my notes?")])
    await conversation.generate()
    conversation.add_tool_result("call_1", "buy milk")

    await conversation.generate()

    assert fake_endpoint.request_bodies[1]["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "What is in my notes?"}]},
        {"id": "rs_1", "type": "reasoning", "summary": [], "encrypted_content": "gAAAAB-opaque"},
        {
            "id": "fc_call_1",
            "type": "function_call",
            "status": "completed",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path": "notes.txt"}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "buy milk"},
    ]


async def test_generating_again_after_a_failed_request_resends_the_same_conversation(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])
    fake_endpoint.fail_next = True
    with pytest.raises(APIStatusError):
        await conversation.generate()

    await conversation.generate()

    assert fake_endpoint.request_bodies[1]["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}
    ]


async def test_generating_again_after_unreadable_tool_arguments_resends_the_same_conversation(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [[tool_call_item("call_1", "read_file", '{"path": ')]]
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1", tools=[READ_FILE])
    conversation.add_user_message([TextPart("What is in my notes?")])
    with pytest.raises(JSONDecodeError):
        await conversation.generate()

    await conversation.generate()

    assert fake_endpoint.request_bodies[1]["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "What is in my notes?"}]}
    ]


async def test_generating_raises_when_the_provider_reports_that_the_model_failed(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.error_next = {"code": "server_error", "message": "the model fell over"}
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])

    with pytest.raises(RuntimeError, match=r"^the model failed: the model fell over$"):
        await conversation.generate()


async def test_generating_sends_an_inline_image_as_a_data_uri_in_its_place_among_the_text(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message(
        [
            TextPart("Before"),
            ImagePart(data="iVBORw==", media_type="image/png"),
            TextPart("After"),
        ]
    )

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["input"][0]["content"] == [
        {"type": "input_text", "text": "Before"},
        {"type": "input_image", "image_url": "data:image/png;base64,iVBORw==", "detail": "auto"},
        {"type": "input_text", "text": "After"},
    ]


async def test_generating_sends_an_image_url_for_the_provider_to_fetch(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([ImageUrlPart(url="https://images.test/cat.png")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["input"][0]["content"] == [
        {"type": "input_image", "image_url": "https://images.test/cat.png", "detail": "auto"}
    ]


@pytest.mark.parametrize(
    "image",
    [
        ImagePart(data="iVBORw==", media_type="image/png"),
        ImageUrlPart(url="https://images.test/cat.png"),
    ],
)
async def test_generating_for_a_model_without_image_support_sends_a_note_in_place_of_an_image(
    image: UserPart, fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(
        client, model="glm-5.3", supports_images=False
    )
    conversation.add_user_message([TextPart("Before"), image, TextPart("After")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["input"][0]["content"] == [
        {"type": "input_text", "text": "Before"},
        {"type": "input_text", "text": "[image omitted: this model cannot view images]"},
        {"type": "input_text", "text": "After"},
    ]


async def test_generating_sends_a_note_in_place_of_audio(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([AudioPart(data="UklGRg==", format="wav")])

    await conversation.generate()

    assert fake_endpoint.request_bodies[0]["input"][0]["content"] == [
        {"type": "input_text", "text": "[audio omitted: this model cannot hear audio]"}
    ]


@pytest.mark.parametrize(
    "shown",
    [
        {"summary": [{"type": "summary_text", "text": "They want pong."}]},
        {"content": [{"type": "reasoning_text", "text": "They want pong."}]},
    ],
)
async def test_generating_returns_the_models_thinking_ahead_of_its_text(
    shown: dict[str, Any], fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [[reasoning_item(**shown), text_item("pong")]]
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("ping")])

    reply = await conversation.generate()

    assert reply == AssistantMessage(content=(ThinkingPart("They want pong."), TextPart("pong")))


async def test_generating_returns_reasoning_the_model_did_not_show_as_no_thinking(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [[reasoning_item(), text_item("pong")]]
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("ping")])

    reply = await conversation.generate()

    assert reply == AssistantMessage(content=(TextPart("pong"),))


async def test_generating_returns_a_refusal_as_the_text_of_the_models_turn(
    fake_endpoint: FakeResponsesEndpoint, client: AsyncOpenAI
) -> None:
    fake_endpoint.replies = [
        [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "I can't help with that."}],
            }
        ]
    ]
    conversation = OpenAIResponsesCompatibleConversation(client, model="gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])

    reply = await conversation.generate()

    assert reply == AssistantMessage(content=(TextPart("I can't help with that."),))
