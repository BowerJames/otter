from pydantic import BaseModel, ConfigDict


class AgentToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    is_error: bool = False
    terminate: bool = False
