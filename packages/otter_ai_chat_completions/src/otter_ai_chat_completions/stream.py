"""The Chat Completions ``AssistantMessageStreamFn`` seam.

This module defines the signature and contract for
:func:`create_chat_completions_assistant_message_stream` — a concrete
implementation of :data:`otter_ai.AssistantMessageStreamFn` for the Chat
Completions wire format.

In this initial version the body raises :class:`NotImplementedError`. The
translation logic (``Context`` <-> request, SSE <-> assistant events), the
httpx transport (abort race, hook invocation, retry/timeout), and behavioural
tests are delivered in a follow-on PR.
"""

from __future__ import annotations

from otter_ai import AssistantMessageStream, Context
from otter_ai_chat_completions.options import ChatCompletionsModelOptions


def create_chat_completions_assistant_message_stream(
    options: ChatCompletionsModelOptions, context: Context
) -> AssistantMessageStream:
    """Build an :class:`~otter_ai.AssistantMessageStream` for a Chat
    Completions model.

    Synchronous; returns immediately and spawns its producer via
    ``asyncio.create_task``. Honours the :data:`~otter_ai.AssistantMessageStreamFn`
    contract:

    * **Never raise.** Request/model/runtime failures are encoded as
      :class:`~otter_ai.AssistantErrorEvent` (with ``stop_reason`` of
      ``"error"`` or ``"aborted"`` and ``error_message`` set).
    * Emit :class:`~otter_ai.AssistantStartEvent` before any partial updates.
    * Every non-terminal event carries a full ``partial`` snapshot of the
      in-progress :class:`~otter_ai.AssistantMessage`.
    * Terminate with **exactly one** of ``done`` / ``error``.
    * Map the provider's ``finish_reason`` onto :data:`~otter_ai.StopReason`.
    * Compute :class:`~otter_ai.Usage` / :class:`~otter_ai.UsageCost` from
      :class:`~otter_ai_chat_completions.ChatCompletionsCost`.

    Hooks (pi-ai parity):

    * ``options.hooks.on_payload`` — awaited pre-send with the fully-built
      request body; a non-``None`` return **replaces** the body.
    * ``options.hooks.on_response`` — awaited post-headers / pre-body with a
      narrow ``{status, headers}`` view; observer, return ignored.

    Abort:

    * Cooperative via ``options.abort_signal``. The transport checks
      ``is_set()`` between SSE chunks (and races the signal against body
      iteration). On abort it emits
      :class:`~otter_ai.AssistantErrorEvent` with ``reason="aborted"`` and
      stops.
    """
    raise NotImplementedError("transport + translation delivered in a follow-on PR")
