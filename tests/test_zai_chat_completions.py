"""Behaviour of Z.ai coding plan conversations, observed on the wire at a fake Z.ai."""

import json

import httpx2
import pytest

from otter.messages import AssistantMessage, AudioPart, ImagePart, TextPart, UserMessage, UserPart
from otter.zai_chat_completions import create_zai_coding_plan_conversations


class FakeZai:
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
                "model": "glm-5.3",
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
def fake_zai() -> FakeZai:
    return FakeZai()


@pytest.fixture
def http_client(fake_zai: FakeZai) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(fake_zai))


async def test_a_conversation_generates_at_the_coding_plan_endpoint_with_the_api_key(
    fake_zai: FakeZai, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_zai_coding_plan_conversations("zai-key", http_client=http_client)
    conversation = create_conversation("glm-5.3")
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    [request] = fake_zai.requests
    assert str(request.url) == "https://api.z.ai/api/coding/paas/v4/chat/completions"
    assert request.headers["authorization"] == "Bearer zai-key"


@pytest.mark.parametrize(
    "part, note",
    [
        (
            ImagePart(data="iVBORw==", media_type="image/png"),
            "[image omitted: this model cannot view images]",
        ),
        (
            AudioPart(data="UklGRg==", format="wav"),
            "[audio omitted: this model cannot hear audio]",
        ),
    ],
)
async def test_a_conversation_sends_a_note_in_place_of_content_the_coding_plan_rejects(
    part: UserPart, note: str, fake_zai: FakeZai, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_zai_coding_plan_conversations("zai-key", http_client=http_client)
    conversation = create_conversation("glm-5.3")
    conversation.add_user_message([part])

    await conversation.generate()

    [request] = fake_zai.requests
    assert json.loads(request.content)["messages"][0]["content"] == [{"type": "text", "text": note}]


async def test_a_conversation_starts_from_the_context_it_is_given(
    fake_zai: FakeZai, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_zai_coding_plan_conversations("zai-key", http_client=http_client)
    conversation = create_conversation(
        "glm-5.3",
        context=[
            UserMessage((TextPart("Hello"),)),
            AssistantMessage((TextPart("Hi there"),)),
        ],
    )
    conversation.add_user_message([TextPart("How are you?")])

    await conversation.generate()

    [request] = fake_zai.requests
    assert json.loads(request.content)["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": [{"type": "text", "text": "How are you?"}]},
    ]
