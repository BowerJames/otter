from typing import Literal

from pydantic import BaseModel


class QueuedUserMessage(BaseModel):
    text: str


class AgentLoopOptions(BaseModel):
    follow_up_queue_mode: Literal["one-by-one", "all-at-once"] = "one-by-one"
    steering_queue_mode: Literal["one-by-one", "all-at-once"] = "all-at-once"
