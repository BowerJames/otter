"""Hook types for the Chat Completions stream.

Mirrors pi-ai's ``onPayload`` / ``onResponse`` hooks, expressed on top of
:data:`otter_ai_core.Hook`:

* :data:`OnPayloadHook` — **mutator**. Fires after the request payload is
  fully built and before it is sent. A non-``None`` return **replaces** the
  payload; ``None`` keeps the original.
* :data:`OnResponseHook` — **observer**. Fires after the response headers are
  received and before the body stream is consumed, with a narrow
  ``{status, headers}`` view. Returns ``None``; the return value is ignored.

Hook events carry the inner :class:`ChatCompletionsModel` (the hooks are
unary, per :data:`otter_ai_core.Hook`), so a hook is reusable across models.

Hooks are async-only. Runtime containers here are :class:`dataclasses`, not
Pydantic models — they hold callables and are not serializable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from otter_ai_chat_completions.models import ChatCompletionsModel
from otter_ai_core import Hook

#: Opaque Chat Completions request body (JSON object).
Payload = dict[str, Any]


@dataclass
class OnPayloadEvent:
    """Trigger for :data:`OnPayloadHook`: the fully-built request body."""

    payload: Payload
    model: ChatCompletionsModel


@dataclass
class OnResponseEvent:
    """Trigger for :data:`OnResponseHook`: a narrow view of the received
    response. The body stream is NOT exposed (it is consumed by the transport
    to produce streaming events)."""

    status: int
    headers: dict[str, str]
    model: ChatCompletionsModel


#: Mutator hook: non-``None`` return replaces the request payload.
type OnPayloadHook = Hook[OnPayloadEvent, Payload | None]

#: Observer hook: the return value is ignored (pi-ai parity).
type OnResponseHook = Hook[OnResponseEvent, None]


@dataclass
class ChatCompletionsHooks:
    """Optional callbacks invoked by the stream around the request lifecycle.

    Both default to ``None`` (no-op). A future transport layer awaits
    ``on_payload`` before send and ``on_response`` after headers arrive.
    """

    on_payload: OnPayloadHook | None = None
    on_response: OnResponseHook | None = None
