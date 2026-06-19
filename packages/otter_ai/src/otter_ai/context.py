"""The top-level conversation context."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from otter_ai.messages import Message
from otter_ai.tools import Tool


class Context(BaseModel):
    """A full conversation: optional system prompt, messages, and tools.

    Designed to be pure-JSON-serializable (``model_dump_json()`` /
    ``model_validate_json()``) so a context can be persisted, transferred, or
    replayed against any model.
    """

    model_config = ConfigDict(extra="forbid")

    system_prompt: str | None = None
    messages: list[Message] = Field(default_factory=list)
    tools: list[Tool] | None = None
