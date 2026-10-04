"""Behaviour of the models otter reaches out of the box, observed on the wire at a fake provider."""

import json
from dataclasses import dataclass

import httpx2
import pytest

from otter.messages import AssistantMessage, TextPart, ToolSpec, UserMessage
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
    """A test adapter for the network: records each request, answers with a plain text turn.

    The turn is in the form of whichever endpoint was asked: chat completions or responses.
    """

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path.endswith("/responses"):
            return httpx2.Response(
                200,
                json={
                    "id": "resp_1",
                    "object": "response",
                    "created_at": 0,
                    "model": "any",
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
    "model_type, provider, url",
    [
        ("chat-completions", "openai", "https://api.openai.com/v1/chat/completions"),
        ("chat-completions", "zai", "https://api.z.ai/api/coding/paas/v4/chat/completions"),
        ("responses", "openai", "https://api.openai.com/v1/responses"),
        ("responses", "zai", "https://api.z.ai/api/v1/responses"),
    ],
)
async def test_a_model_is_reached_at_its_providers_endpoint_for_its_type_with_the_api_key(
    model_type: str,
    provider: str,
    url: str,
    fake_provider: FakeProvider,
    http_client: httpx2.AsyncClient,
) -> None:
    create_model = create_model_factory(http_client)
    model = create_model(Config("some-model", model_type, provider), "secret-key")
    conversation = model(None, [], [])
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
    conversation = model("Be brief.", [ECHO], [])
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


@pytest.mark.parametrize(
    "model_type, history",
    [
        ("chat-completions", "messages"),
        ("responses", "input"),
    ],
)
async def test_a_models_conversations_start_from_the_context_given(
    model_type: str,
    history: str,
    fake_provider: FakeProvider,
    http_client: httpx2.AsyncClient,
) -> None:
    create_model = create_model_factory(http_client)
    model = create_model(Config("some-model", model_type, "openai"), "secret-key")
    conversation = model(
        None, [], [UserMessage((TextPart("Hello"),)), AssistantMessage((TextPart("Hi there"),))]
    )

    await conversation.generate()

    [request] = fake_provider.requests
    assert json.loads(request.content)[history][1] == {"role": "assistant", "content": "Hi there"}


def test_a_model_type_that_is_not_known_is_refused(http_client: httpx2.AsyncClient) -> None:
    create_model = create_model_factory(http_client)

    with pytest.raises(ValueError, match=r"^unknown model type 'telepathy'$"):
        create_model(Config("gpt-5.1", "telepathy", "openai"), "secret-key")


@pytest.mark.parametrize("model_type", ["chat-completions", "responses"])
def test_a_provider_that_does_not_serve_the_model_type_is_refused(
    model_type: str, http_client: httpx2.AsyncClient
) -> None:
    create_model = create_model_factory(http_client)

    with pytest.raises(
        ValueError, match=rf"^provider 'acme' does not serve '{model_type}' models$"
    ):
        create_model(Config("some-model", model_type, "acme"), "secret-key")
