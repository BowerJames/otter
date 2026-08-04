from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.data_models.context.context_item import ContextItem
from otter_ai_core.data_models.context.tool import Tool


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: str | None = None
    items: list[ContextItem] = Field(default_factory=list)
    tools: list[Tool] | None = None
