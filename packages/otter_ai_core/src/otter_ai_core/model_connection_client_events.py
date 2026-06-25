from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from otter_ai_core.messages import Message


class MessageAddEvent(BaseModel):
    """A new message to add to the context."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["message.add"]
    message: Message


class ResponseCreate(BaseModel):
    """Tell the model to start generating a response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["response.create"]


#: Discriminated union of all model connection client events.
ModelConnectionClientEvent = Annotated[
    MessageAddEvent | ResponseCreate,
    Field(discriminator="type"),
]
