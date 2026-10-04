"""Behaviour of the models otter reaches out of the box, observed on the wire at a fake provider."""

import json
from dataclasses import dataclass

import httpx2
import pytest

from otter.messages import TextPart, ToolSpec
from otter.model_factory import create_model_factory


@dataclass(frozen=True)
class Config:
    model_name: str
    model_type: str
    provider: str


ECHO = ToolSpec(
    name="echo",
    description="Repeat the text",
    parameters={"type": "object", "properties": {"text": {"type": "string"}}},
)


class FakeProvider:
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
                "model": "any",
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
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def http_client(fake_provider: FakeProvider) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(fake_provider))


@pytest.mark.parametrize(
    "provider, url",
    [
        ("openai", "https://api.openai.com/v1/chat/completions"),
        ("zai", "https://api.z.ai/api/coding/paas/v4/chat/completions"),
    ],
)
async def test_a_chat_completions_model_is_reached_at_its_provider_with_the_api_key(
    provider: str, url: str, fake_provider: FakeProvider, http_client: httpx2.AsyncClient
) -> None:
    create_model = create_model_factory(http_client)
    model = create_model(Config("some-model", "chat-completions", provider), "secret-key")
    conversation = model(None, [])
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    [request] = fake_provider.requests
    assert str(request.url) == url
    assert request.headers["authorization"] == "Bearer secret-key"


async def test_a_models_conversations_use_its_name_and_the_system_prompt_and_tools_given(
    fake_provider: FakeProvider, http_client: httpx2.AsyncClient
) -> None:
    create_model = create_model_factory(http_client)
    model = create_model(Config("glm-5.3", "chat-completions", "zai"), "secret-key")
    conversation = model("Be brief.", [ECHO])
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    [request] = fake_provider.requests
    body = json.loads(request.content)
    assert body["model"] == "glm-5.3"
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Repeat the text",
                "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
            },
        }
    ]


def test_a_model_type_that_is_not_known_is_refused(http_client: httpx2.AsyncClient) -> None:
    create_model = create_model_factory(http_client)

    with pytest.raises(ValueError, match=r"^unknown model type 'responses'$"):
        create_model(Config("gpt-5.1", "responses", "openai"), "secret-key")


def test_a_provider_that_does_not_serve_the_model_type_is_refused(
    http_client: httpx2.AsyncClient,
) -> None:
    create_model = create_model_factory(http_client)

    with pytest.raises(
        ValueError, match=r"^provider 'acme' does not serve 'chat-completions' models$"
    ):
        create_model(Config("some-model", "chat-completions", "acme"), "secret-key")
