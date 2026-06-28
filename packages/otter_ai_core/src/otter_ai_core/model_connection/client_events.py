from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.context.context_item import ContextItem


class ClientEventTypes(StrEnum):
    AddContextItem = "context_item.add"
    CreateResponse = "response.create"


class ContextItemAddEvent(BaseModel):
    """A new context item to add to the context."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientEventTypes.AddContextItem]
    item: ContextItem


class ResponseCreate(BaseModel):
    """Tell the model to start generating a response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[ClientEventTypes.CreateResponse]


#: Discriminated union of all model connection client events.
ClientEvent = Annotated[
    ContextItemAddEvent | ResponseCreate,
    Field(discriminator="type"),
]
