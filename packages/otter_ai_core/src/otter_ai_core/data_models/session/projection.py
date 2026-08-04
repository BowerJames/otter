from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from otter_ai_core.data_models.context import Context
from otter_ai_core.data_models.provider import ThinkingLevel


class SessionDerivedState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: tuple[str, str] | None
    thinking_level: ThinkingLevel | None
    active_tool_names: list[str] | None


class SessionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: Context
    state: SessionDerivedState


__all__ = [
    "SessionDerivedState",
    "SessionProjection",
]
