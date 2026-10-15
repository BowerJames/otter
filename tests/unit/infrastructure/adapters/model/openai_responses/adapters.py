"""Test adapters for the network the responses adapter's client reaches."""

import json
from typing import Any

import httpx2
from openai import AsyncOpenAI


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
    """Records each request body, and answers with the next of `replies`.

    Each reply is the output items of one turn; once they run out, it answers with a
    plain text turn. Setting `error_next` makes the next response report that the model
    failed.
    """

    def __init__(self) -> None:
        self.request_bodies: list[Any] = []
        self.replies: list[list[dict[str, Any]]] = []
        self.error_next: dict[str, Any] | None = None

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.request_bodies.append(json.loads(request.content))
        if self.error_next:
            error, self.error_next = self.error_next, None
            return httpx2.Response(200, json=self._response("failed", error, []))
        output = self.replies.pop(0) if self.replies else [text_item("OK")]
        return httpx2.Response(200, json=self._response("completed", None, output))

    def client(self) -> AsyncOpenAI:
        """A client whose requests this endpoint answers."""
        return AsyncOpenAI(
            base_url="https://provider.test/v1",
            api_key="test-key",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self)),
        )

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
