from enum import StrEnum


class Role(StrEnum):
    User = "user"
    Assistant = "assistant"
    ToolResult = "tool_result"
