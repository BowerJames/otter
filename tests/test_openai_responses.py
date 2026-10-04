"""Behaviour of OpenAI responses conversations, observed on the wire at a fake OpenAI."""

import json

import httpx2
import pytest

from otter.messages import ImagePart, TextPart
from otter.openai_responses import create_openai_responses_conversations


class FakeOpenAI:
    """A test adapter for the network: records each request, answers with a plain text turn."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "created_at": 0,
                "model": "gpt-5.1",
                "status": "completed",
                "error": None,
                "output": [
                    {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "OK", "annotations": []}],
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
    create_conversation = create_openai_responses_conversations(
        "openai-key", http_client=http_client
    )
    conversation = create_conversation("gpt-5.1")
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    [request] = fake_openai.requests
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["authorization"] == "Bearer openai-key"


async def test_a_conversation_sends_images_to_the_model(
    fake_openai: FakeOpenAI, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_openai_responses_conversations(
        "openai-key", http_client=http_client
    )
    conversation = create_conversation("gpt-5.1")
    conversation.add_user_message([ImagePart(data="iVBORw==", media_type="image/png")])

    await conversation.generate()

    [request] = fake_openai.requests
    assert json.loads(request.content)["input"][0]["content"] == [
        {"type": "input_image", "image_url": "data:image/png;base64,iVBORw==", "detail": "auto"}
    ]
