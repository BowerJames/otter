"""An agent session built by the production factories, run against a fake provider endpoint."""

import json
from typing import Any

import httpx2
import pytest

from otter.core.agent_session import Idle, SessionEvent
from otter.core.domain.messages import AssistantMessage, TextPart, UserMessage
from otter.infrastructure.factories.modules.agent_session import create_agent_session
from otter.infrastructure.factories.modules.model import create_model

pytestmark = pytest.mark.e2e


async def test_a_prompt_is_answered_by_the_providers_model_reached_with_its_key() -> None:
    requests: list[httpx2.Request] = []

    def endpoint(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
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
                        "message": {"role": "assistant", "content": "Hi there"},
                    }
                ],
            },
        )

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint))
    model = create_model("chat-completions", "zai", "glm-5.3", "zai-key", http_client=http_client)
    session = create_agent_session(model, system_prompt="Be brief.")

    events: list[SessionEvent] = []
    async with session:
        session.prompt("Hello")
        async for event in session.stream():
            events.append(event)
            if isinstance(event, Idle):
                break

    assert events == [
        UserMessage((TextPart("Hello"),)),
        AssistantMessage((TextPart("Hi there"),)),
        Idle(),
    ]
    [request] = requests
    assert str(request.url) == "https://api.z.ai/api/coding/paas/v4/chat/completions"
    assert request.headers["authorization"] == "Bearer zai-key"
    body: dict[str, Any] = json.loads(request.content)
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
