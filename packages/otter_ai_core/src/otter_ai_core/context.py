"""The top-level conversation context."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.context_item import ContextItem
from otter_ai_core.tools import Tool


class Context(BaseModel):
    """A full conversation: optional system prompt, items, and tools.

    Designed to be pure-JSON-serializable (``model_dump_json()`` /
    ``model_validate_json()``) so a context can be persisted, transferred, or
    replayed against any model.
    """

    model_config = ConfigDict(extra="forbid")

    system_prompt: str | None = None
    items: list[ContextItem] = Field(default_factory=list)
    tools: list[Tool] | None = None
