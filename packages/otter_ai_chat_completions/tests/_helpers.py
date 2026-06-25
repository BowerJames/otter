"""Shared fixtures for ``otter_ai_chat_completions`` tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest

from otter_ai_chat_completions import (
    ChatCompletionsCost,
    ChatCompletionsModel,
    ChatCompletionsModelOptions,
)
from otter_ai_chat_completions import stream as stream_module
from otter_ai_core import Context, ContextItem, UserMessage


def make_model(**overrides: Any) -> ChatCompletionsModel:
    base: dict[str, Any] = {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "reasoning": False,
        "input_modalities": ["text"],
        "context_window": 128_000,
        "max_tokens": 16_384,
        "cost": ChatCompletionsCost(
            input=2.5, output=10.0, cache_read=1.25, cache_write=0.0
        ),
        "api_key": "sk-test",
    }
    base.update(overrides)
    return ChatCompletionsModel(**base)


def make_options(**overrides: Any) -> ChatCompletionsModelOptions:
    model = overrides.pop("model", make_model())
    return ChatCompletionsModelOptions(model=model, **overrides)


def simple_context(text: str = "hello") -> Context:
    return Context(
        system_prompt=None,
        items=[
            ContextItem(
                id="u1", message=UserMessage(role="user", content=text, timestamp=0)
            )
        ],
    )


def sse_response(
    chunks: Sequence[dict[str, Any]] | None, status: int = 200
) -> httpx.Response:
    """Build a streaming SSE response carrying ``chunks`` as JSON ``data:`` lines."""
    body_lines: list[str] = []
    if chunks is not None:
        for chunk in chunks:
            body_lines.append("data: " + json.dumps(chunk))
        body_lines.append("data: [DONE]")
    content = ("\n\n".join(body_lines) + "\n\n").encode("utf-8") if body_lines else b""
    return httpx.Response(
        status_code=status,
        headers={"content-type": "text/event-stream"},
        content=content,
    )


def error_response(status: int, body: str = "boom") -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers={"content-type": "application/json"},
        content=body.encode(),
    )


@pytest.fixture
def monkeypatch_fixture(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Expose ``monkeypatch`` as a fixture for helper functions that need it."""
    return monkeypatch


def install_fake_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> None:
    """Monkeypatch ``_create_client`` to use an ``httpx.MockTransport``.

    ``handler`` is the ``MockTransport`` callable (receives an
    :class:`httpx.Request`, returns an :class:`httpx.Response`). The returned
    client keeps the handler's responses, so streaming + retries both flow
    through it.
    """
    transport = httpx.MockTransport(handler)

    def fake_create_client(
        model: ChatCompletionsModel,
        api_key: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> httpx.AsyncClient:
        del timeout_seconds  # the fake transport ignores the timeout
        return httpx.AsyncClient(
            base_url=model.base_url,
            headers={**headers, "Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    monkeypatch.setattr(stream_module, "_create_client", fake_create_client)


async def collect(stream: Any) -> list[Any]:
    return [event async for event in stream]
