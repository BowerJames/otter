"""Build the opening ``session.update`` body."""

from __future__ import annotations

from typing import Any

from otter_ai_core import Tool
from otter_ai_realtime._messages import convert_tools
from otter_ai_realtime.options import RealtimeModelOptions


def build_session_update(
    options: RealtimeModelOptions,
    system_prompt: str | None,
    tools: list[Tool],
) -> dict[str, Any]:
    """Assemble the Realtime ``session.update`` frame.

    The ``session`` object is built from the context (``instructions`` from
    ``system_prompt``, ``tools`` from the context tools) plus the non-``None``
    fields of :attr:`RealtimeModelOptions.session_config`. ``None`` config
    fields are omitted so the server applies its own defaults.

    Returns the full frame ``{"type": "session.update", "session": {...}}``;
    the ``session`` object alone is exposed via :func:`build_session_body` for
    the :data:`~otter_ai_realtime.hooks.OnSessionUpdateHook` event.
    """
    session = build_session_body(options, system_prompt, tools)
    return {"type": "session.update", "session": session}


def build_session_body(
    options: RealtimeModelOptions,
    system_prompt: str | None,
    tools: list[Tool],
) -> dict[str, Any]:
    """Build just the ``session`` object (the hook event payload)."""
    session: dict[str, Any] = {}
    if system_prompt:
        session["instructions"] = system_prompt

    config = options.session_config
    if config.voice is not None:
        session["voice"] = config.voice
    if config.modalities is not None:
        session["modalities"] = list(config.modalities)
    if config.temperature is not None:
        session["temperature"] = config.temperature
    if config.max_response_output_tokens is not None:
        session["max_response_output_tokens"] = config.max_response_output_tokens
    if config.turn_detection is not None:
        session["turn_detection"] = dict(config.turn_detection)

    converted_tools = convert_tools(tools)
    if converted_tools:
        session["tools"] = converted_tools
    return session


__all__ = ["build_session_body", "build_session_update"]
