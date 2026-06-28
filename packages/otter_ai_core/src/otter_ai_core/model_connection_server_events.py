from typing import Literal

from pydantic import BaseModel, ConfigDict

from otter_ai_core.context.context_item import AssistantContextItem, ContextItem


class ContextItemAddedEvent(BaseModel):
    """A new context item has been added to the context."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["context_item.added"]
    item: ContextItem


class AssistantItemStartedEvent(BaseModel):
    """The assistant has started generating a response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["assistant_item.started"]
    partial: AssistantContextItem
