"""The data a model is given."""

from dataclasses import dataclass

from otter.core.domain.messages import ContextEntry, ToolSpec


@dataclass(frozen=True)
class ModelInput:
    """What a model is shown to produce its next turn.

    `system` is the system prompt it sees ahead of everything else, or None for none,
    `tools` are the tools it may ask to have called, and `context` is the conversation
    so far, oldest first.
    """

    system: str | None
    tools: tuple[ToolSpec, ...]
    context: tuple[ContextEntry, ...]
