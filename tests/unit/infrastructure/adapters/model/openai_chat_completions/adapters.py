"""Test adapters for the network the chat completions adapter's client reaches."""

import json
from typing import Any

import httpx2
from openai import AsyncOpenAI


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
    """Records each request body, and answers with the next of `replies`.

    Once they run out, it answers with a plain text turn.
    """

    def __init__(self) -> None:
        self.request_bodies: list[Any] = []
        self.replies: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.request_bodies.append(json.loads(request.content))
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

    def client(self) -> AsyncOpenAI:
        """A client whose requests this endpoint answers."""
        return AsyncOpenAI(
            base_url="https://provider.test/v1",
            api_key="test-key",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self)),
        )
