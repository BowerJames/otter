"""Behaviour of OpenAI conversations, observed on the wire at a fake OpenAI."""

import json

import httpx2
import pytest

from otter.messages import AssistantMessage, AudioPart, ImagePart, TextPart, UserMessage
from otter.openai_chat_completions import create_openai_conversations


class FakeOpenAI:
    """A test adapter for the network: records each request, answers with a plain text turn."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-5.1",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OK"},
                    }
                ],
            },
        )


@pytest.fixture
def fake_openai() -> FakeOpenAI:
    return FakeOpenAI()


@pytest.fixture
def http_client(fake_openai: FakeOpenAI) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(fake_openai))


async def test_a_conversation_generates_at_the_openai_endpoint_with_the_api_key(
    fake_openai: FakeOpenAI, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_openai_conversations("openai-key", http_client=http_client)
    conversation = create_conversation("gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    [request] = fake_openai.requests
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer openai-key"


async def test_a_conversation_sends_a_note_in_place_of_audio(
    fake_openai: FakeOpenAI, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_openai_conversations("openai-key", http_client=http_client)
    conversation = create_conversation("gpt-5.1")
    conversation.add_user_message([AudioPart(data="UklGRg==", format="wav")])

    await conversation.generate()

    [request] = fake_openai.requests
    assert json.loads(request.content)["messages"][0]["content"] == [
        {"type": "text", "text": "[audio omitted: this model cannot hear audio]"}
    ]


async def test_a_conversation_sends_images_to_the_model(
    fake_openai: FakeOpenAI, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_openai_conversations("openai-key", http_client=http_client)
    conversation = create_conversation("gpt-5.1")
    conversation.add_user_message([ImagePart(data="iVBORw==", media_type="image/png")])

    await conversation.generate()

    [request] = fake_openai.requests
    assert json.loads(request.content)["messages"][0]["content"] == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw=="}}
    ]


async def test_a_conversation_starts_from_the_context_it_is_given(
    fake_openai: FakeOpenAI, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_openai_conversations("openai-key", http_client=http_client)
    conversation = create_conversation(
        "gpt-5.1",
        context=[
            UserMessage((TextPart("Hello"),)),
            AssistantMessage((TextPart("Hi there"),)),
        ],
    )
    conversation.add_user_message([TextPart("How are you?")])

    await conversation.generate()

    [request] = fake_openai.requests
    assert json.loads(request.content)["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": [{"type": "text", "text": "How are you?"}]},
    ]
