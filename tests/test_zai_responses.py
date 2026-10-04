"""Behaviour of Z.ai coding plan responses conversations, observed on the wire at a fake Z.ai."""

import json

import httpx2
import pytest

from otter.messages import ImagePart, TextPart
from otter.zai_responses import create_zai_coding_plan_responses_conversations


class FakeZai:
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
                "model": "glm-5.3",
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
def fake_zai() -> FakeZai:
    return FakeZai()


@pytest.fixture
def http_client(fake_zai: FakeZai) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(fake_zai))


async def test_a_conversation_generates_at_the_coding_plan_responses_endpoint_with_the_api_key(
    fake_zai: FakeZai, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_zai_coding_plan_responses_conversations(
        "zai-key", http_client=http_client
    )
    conversation = create_conversation("glm-5.3")
    conversation.add_user_message([TextPart("Hello")])

    await conversation.generate()

    [request] = fake_zai.requests
    assert str(request.url) == "https://api.z.ai/api/v1/responses"
    assert request.headers["authorization"] == "Bearer zai-key"


async def test_a_conversation_sends_a_note_in_place_of_an_image(
    fake_zai: FakeZai, http_client: httpx2.AsyncClient
) -> None:
    create_conversation = create_zai_coding_plan_responses_conversations(
        "zai-key", http_client=http_client
    )
    conversation = create_conversation("glm-5.3")
    conversation.add_user_message([ImagePart(data="iVBORw==", media_type="image/png")])

    await conversation.generate()

    [request] = fake_zai.requests
    assert json.loads(request.content)["input"][0]["content"] == [
        {"type": "input_text", "text": "[image omitted: this model cannot view images]"}
    ]
