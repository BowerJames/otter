from pydantic import BaseModel, ConfigDict

from otter_ai_core.context import UserContent


class AgentToolResult[TDetails](BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: list[UserContent]
    details: TDetails
    is_error: bool = False
    terminate: bool = False
