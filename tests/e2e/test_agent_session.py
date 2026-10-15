"""An agent session built by the production factories, run against a fake provider endpoint."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

from otter.core.agent_session import AgentSession, Idle, SessionEvent
from otter.core.domain.messages import AssistantMessage, TextPart, UserMessage
from otter.core.model import Model
from otter.infrastructure.factories.modules.agent_session import create_agent_session
from otter.infrastructure.factories.modules.model import create_model
from otter.infrastructure.factories.modules.session_log import create_file_session_log

pytestmark = pytest.mark.e2e


def says(text: str) -> dict[str, Any]:
    """A chat completions response in which the model says `text`."""
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}
        ],
    }


def responds(text: str) -> dict[str, Any]:
    """A responses response in which the model says `text`."""
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "m",
        "status": "completed",
        "error": None,
        "output": [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
    }


async def until_idle(session: AgentSession) -> list[SessionEvent]:
    events: list[SessionEvent] = []
    async for event in session.stream():
        events.append(event)
        if isinstance(event, Idle):
            break
    return events


@pytest.mark.parametrize(
    "model_type, provider, url, reply",
    [
        ("chat-completions", "openai", "https://api.openai.com/v1/chat/completions", says),
        ("chat-completions", "zai", "https://api.z.ai/api/coding/paas/v4/chat/completions", says),
        ("responses", "openai", "https://api.openai.com/v1/responses", responds),
        ("responses", "zai", "https://api.z.ai/api/v1/responses", responds),
    ],
)
async def test_each_model_is_reached_at_its_providers_endpoint_with_the_key(
    model_type: str, provider: str, url: str, reply: Callable[[str], dict[str, Any]]
) -> None:
    requests: list[httpx2.Request] = []

    def endpoint(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=reply("Hi there"))

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint))
    session = create_agent_session(
        create_model(model_type, provider, "m", "the-key", http_client=http_client)
    )

    async with session:
        session.prompt("Hello")
        events = await until_idle(session)

    assert events[1] == AssistantMessage((TextPart("Hi there"),))
    [request] = requests
    assert str(request.url) == url
    assert request.headers["authorization"] == "Bearer the-key"


async def test_sessions_made_without_a_log_each_keep_their_own_context() -> None:
    def endpoint(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=says("Hi there"))

    def model() -> Model:
        http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint))
        return create_model("chat-completions", "openai", "m", "the-key", http_client=http_client)

    first = create_agent_session(model())
    async with first:
        first.prompt("Hello")
        await until_idle(first)

    second = create_agent_session(model())
    async with second:
        assert list(second.history()) == []


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


async def test_a_session_kept_in_a_file_is_picked_up_by_the_next_session_on_that_file(
    tmp_path: Path,
) -> None:
    def endpoint(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=says("Hi there"))

    def model() -> Model:
        http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint))
        return create_model("chat-completions", "openai", "m", "the-key", http_client=http_client)

    path = tmp_path / "session.jsonl"
    first = create_agent_session(model(), session_log=create_file_session_log(path))
    async with first:
        first.prompt("Hello")
        await until_idle(first)

    second = create_agent_session(model(), session_log=create_file_session_log(path))
    async with second:
        assert list(second.history()) == [
            UserMessage((TextPart("Hello"),)),
            AssistantMessage((TextPart("Hi there"),)),
        ]
