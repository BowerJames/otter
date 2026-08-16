from pydantic import BaseModel


class AgentToolResult(BaseModel):
    text: str
    is_error: bool = False
    terminate: bool = False
