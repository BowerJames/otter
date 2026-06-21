"""Thinking-level clamping (port of pi-ai's ``models.ts``).

pi-ai clamps a requested thinking level against the levels a model supports
(derived from its ``reasoning`` capability and its ``thinking_level_map``).
This is the layer otter deliberately skipped in
:mod:`otter_ai_chat_completions` (issue #13 decision #4); it lives here, one
level up, where catalog facts are available.

The supported-level rules mirror pi-ai exactly:

* a non-reasoning model supports only ``"off"``;
* a level explicitly mapped to ``None`` is unsupported;
* ``"xhigh"`` is supported only when *explicitly* mapped to a non-``None``
  value (an absent key is treated as unsupported, matching pi-ai);
* every other level defaults to supported when absent from the map.

``clamp_thinking_level`` returns the requested level when supported, else
walks outward (up then down) over the ordered level ladder, falling back to
the first supported level (or ``"off"``).

The distinction between an *absent* map key and an *explicit-None* value
matters: ``None`` marks a level unsupported, while an absent key means "use
the default for that level". This mirrors the TypeScript ``undefined`` /
``null`` split in pi-ai.
"""

from __future__ import annotations

from otter_ai_assistant_provider_stream.types import ThinkingLevel
from otter_ai_chat_completions import (
    ChatCompletionsModel,
    ChatCompletionsReasoningEffort,
)

#: Ordered ladder of all thinking levels (pi-ai ``EXTENDED_THINKING_LEVELS``).
_THINKING_LEVELS: list[ThinkingLevel] = [
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
]


def get_supported_thinking_levels(
    model: ChatCompletionsModel,
) -> list[ThinkingLevel]:
    """Thinking levels the ``model`` supports.

    Mirrors pi-ai's ``getSupportedThinkingLevels``: non-reasoning models
    support only ``"off"``; reasoning models support every level not mapped to
    ``None``, with ``"xhigh"`` requiring an explicit non-``None`` mapping.
    """
    if not model.reasoning:
        return ["off"]

    level_map = model.thinking_level_map
    supported: list[ThinkingLevel] = []
    for level in _THINKING_LEVELS:
        if level_map is not None and level in level_map:
            # Key present in the map. A ``None`` value marks the level
            # unsupported (pi-ai ``mapped === null``).
            if level_map[level] is None:
                continue
            mapped_is_defined = True
        else:
            mapped_is_defined = False

        if level == "xhigh":
            # xhigh requires an explicit non-None mapping; absent -> unsupported.
            if mapped_is_defined:
                supported.append(level)
            continue
        # All other levels default to supported when absent.
        supported.append(level)
    return supported


def clamp_thinking_level(
    model: ChatCompletionsModel, level: ThinkingLevel
) -> ThinkingLevel:
    """Clamp ``level`` to a level the ``model`` supports.

    Mirrors pi-ai's ``clampThinkingLevel``: if the requested level is
    supported, return it; otherwise scan upward from the requested position
    for the next supported level, then downward, falling back to the first
    supported level or ``"off"``.
    """
    available = get_supported_thinking_levels(model)
    if level in available:
        return level

    requested_index = _THINKING_LEVELS.index(level)
    # Scan upward for a higher supported level.
    for i in range(requested_index, len(_THINKING_LEVELS)):
        candidate = _THINKING_LEVELS[i]
        if candidate in available:
            return candidate
    # Then downward.
    for i in range(requested_index - 1, -1, -1):
        candidate = _THINKING_LEVELS[i]
        if candidate in available:
            return candidate
    return available[0] if available else "off"


def resolve_reasoning_effort(
    level: ThinkingLevel,
) -> ChatCompletionsReasoningEffort | None:
    """Map a clamped thinking level to the chat-completions ``reasoning_effort``.

    ``"off"`` -> ``None`` (the chat-completions layer then omits the reasoning
    field). Any other level becomes the matching
    :data:`~otter_ai_chat_completions.ChatCompletionsReasoningEffort`; the
    provider-specific mapping via ``thinking_level_map`` is applied downstream
    by ``otter_ai_chat_completions._params``.
    """
    if level == "off":
        return None
    return level


__all__ = [
    "ThinkingLevel",
    "clamp_thinking_level",
    "get_supported_thinking_levels",
    "resolve_reasoning_effort",
]
