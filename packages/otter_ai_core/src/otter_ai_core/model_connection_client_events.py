from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.context_item import ContextItem


class ContextItemAddEvent(BaseModel):
    """A new context item to add to the context."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["context_item.add"]
    item: ContextItem


class ResponseCreate(BaseModel):
    """Tell the model to start generating a response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["response.create"]


class ResponseAbort(BaseModel):
    """Tell the model to abort generating a response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["response.abort"]


#: Discriminated union of all model connection client events.
ModelConnectionClientEvent = Annotated[
    ContextItemAddEvent | ResponseCreate | ResponseAbort,
    Field(discriminator="type"),
]
