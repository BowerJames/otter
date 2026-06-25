from pydantic import BaseModel, ConfigDict

from otter_ai_core.messages import Message


class ContextItem(BaseModel):
    """A single item in the conversation context."""

    model_config = ConfigDict(extra="forbid")

    id: str
    message: Message
