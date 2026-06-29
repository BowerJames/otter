"""Shared test helpers for the assistant-provider-stream tests.

Includes both catalog-model factories (for unit tests) and a thin copy of the
httpx transport-faking helpers from ``otter_ai_chat_completions`` (for the
end-to-end seam test). The transport helpers are copied rather than imported
from the sibling package because its ``tests`` module is not shipped with the
wheel.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest

from otter_ai_assistant_provider_stream import (
    create_assistant_message_stream_by_provider,
)
from otter_ai_chat_completions import (
    ChatCompletionsCost,
    ChatCompletionsModel,
)
from otter_ai_chat_completions import stream as stream_module
from otter_ai_core import Context, UserMessage, context_item
from otter_ai_core.assistant_message_stream import AssistantMessageStream


def model_kwargs(**overrides: Any) -> dict[str, Any]:
    """Minimal valid ``ChatCompletionsModel`` kwargs (provider/model overrideable).

    Returns a dict of sensible defaults so tests can build a catalog model
    with ``ChatCompletionsModel(**model_kwargs(reasoning=False, ...))``. The
    ``provider``/``id`` defaults are non-built-in so a test model never
    collides with a real catalog entry.
    """
    base: dict[str, Any] = {
        "id": "test-model",
        "name": "Test Model",
        "provider": "test-provider",
        "base_url": "https://example.test/v1",
        "api": "chat-completions",
        "reasoning": True,
        "input_modalities": ["text"],
        "context_window": 8192,
        "max_tokens": 4096,
        "cost": ChatCompletionsCost(
            input=1.0, output=2.0, cache_read=0.5, cache_write=0.0
        ),
    }
    base.update(overrides)
    return base


def simple_context(text: str = "hello") -> Context:
    return Context(
        system_prompt=None,
        items=[
            context_item(
                message=UserMessage(role="user", content=text, timestamp=0), id="u1"
            )
        ],
    )


def start_stream(
    options: Any,
    context: Context,
    abort: asyncio.Event | None = None,
) -> AssistantMessageStream:
    """Two-step convenience: build the provider-dispatch stream fn, then call it.

    The seam is a builder — ``create_assistant_message_stream_by_provider``
    takes ``options`` and returns an ``AssistantMessageStreamFn``, which is then
    called with ``(context, abort)``. Behavioural tests rarely exercise the
    abort signal, so this helper defaults it to a fresh, unset
    :class:`asyncio.Event`.
    """
    if abort is None:
        abort = asyncio.Event()
    return create_assistant_message_stream_by_provider(options)(context, abort)


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


def install_fake_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    """Monkeypatch the chat-completions ``_create_client`` to use a ``MockTransport``.

    Mirrors the faking seam from issue #13 decision #10. The transport is
    shared across sends so streaming + retries both flow through ``handler``.
    """
    transport = httpx.MockTransport(handler)

    def fake_create_client(
        model: ChatCompletionsModel,
        api_key: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> httpx.AsyncClient:
        del timeout_seconds
        return httpx.AsyncClient(
            base_url=model.base_url,
            headers={**headers, "Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    monkeypatch.setattr(stream_module, "_create_client", fake_create_client)


async def collect(stream: Any) -> list[Any]:
    return [event async for event in stream]
