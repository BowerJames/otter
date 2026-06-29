"""Realtime model + session-config definitions for the wire-format contract.

This module is **pure data**: identity + capabilities (on
:class:`RealtimeModel`) and the per-session ``session.update`` body (on
:class:`RealtimeSessionConfig`). It performs no provider/base_url detection,
no env-key resolution, and no transport behaviour — those are the consumer's
responsibility. The connection function (:mod:`otter_ai_realtime.connection`)
reads these values verbatim.

Conventions follow :mod:`otter_ai_core` and :mod:`otter_ai_chat_completions`:
Pydantic v2, ``extra="forbid"``, snake_case, ``X | None = None`` optionals,
JSON round-trippable.

v1 is text-only: :attr:`RealtimeModel.input_modalities` and
:attr:`RealtimeSessionConfig.modalities` are pinned to ``["text"]``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

#: The single API shape this package speaks. Constant for the whole package;
#: stored on the model so it flows onto ``AssistantMessage.api`` (inert
#: provenance in otter).
RealtimeApi = Literal["realtime"]


class RealtimeCost(BaseModel):
    """Pricing rates in USD per million tokens.

    Used to compute :class:`otter_ai_core.UsageCost` per turn. This is **not** a
    per-turn accounting record — it is a rate card. Mirrors
    :class:`otter_ai_chat_completions.ChatCompletionsCost`.
    """

    model_config = ConfigDict(extra="forbid")

    input: float
    output: float
    cache_read: float
    cache_write: float


class RealtimeModel(BaseModel):
    """A realtime model plus its connection-level configuration.

    Pure configuration: identity + capabilities + connection shaping. No
    behaviour, no detection, no env magic. The connection function reads it
    verbatim. Per-session request shaping (voice, turn detection, …) lives on
    :class:`RealtimeSessionConfig`, not here — it is bundled with the model in
    :class:`otter_ai_realtime.options.RealtimeModelOptions`.

    Runtime handles (hooks) do **not** live here — they are bundled with the
    model in :class:`RealtimeModelOptions`; the connection-cancel signal is the
    seam's third argument (an :class:`asyncio.Event`).
    """

    model_config = ConfigDict(extra="forbid")

    # --- Identity (feeds inert ``AssistantMessage`` provenance) ---
    id: str
    name: str
    #: Provenance only. NOT read for behaviour in this package.
    provider: str
    base_url: str
    api: RealtimeApi = "realtime"

    # --- Capabilities (catalog facts) ---
    #: v1 is text-only. The literal pins the union so audio cannot sneak in
    #: until the content model grows an :class:`~otter_ai_core.AudioContent`.
    input_modalities: list[Literal["text"]]
    context_window: int
    #: The model's own output-token cap.
    max_tokens: int
    cost: RealtimeCost

    # --- Connection shaping (per-connection serializable config) ---
    api_key: str | None = None
    headers: dict[str, str] | None = None
    #: WebSocket connect timeout (seconds). ``None`` = library default.
    timeout_ms: int | None = None


class RealtimeSessionConfig(BaseModel):
    """The opening ``session.update`` body, minus identity-derived fields.

    Every field is optional: ``None`` means "do not send the key; let the
    server use its default". This bundle realises the per-session request
    shaping that, on :class:`otter_ai_chat_completions.ChatCompletionsModel`,
    lives on the model itself — but realtime's per-session surface is large
    and largely orthogonal to the catalog facts, so it is kept separate.

    ``instructions`` is intentionally absent — it comes from
    :class:`otter_ai_core.Context.system_prompt`. ``tools`` is also absent —
    it comes from :class:`otter_ai_core.Context.tools`.
    """

    model_config = ConfigDict(extra="forbid")

    #: The voice the model speaks with (server-defined voice ids). Text-only
    #: v1 still sends this if set; servers ignore it for text-only sessions.
    voice: str | None = None
    #: v1 is text-only. Always ``["text"]`` when set.
    modalities: list[Literal["text"]] | None = None
    temperature: float | None = None
    #: Per-response output cap (server ``max_response_output_tokens``).
    max_response_output_tokens: int | None = None
    #: Server VAD / turn-detection config blob, passed through verbatim
    #: (e.g. ``{"type": "server_vad", "threshold": 0.5}``). ``None`` = omit.
    turn_detection: dict[str, Any] | None = None
