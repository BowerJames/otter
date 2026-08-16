import asyncio
from collections.abc import Awaitable

from otter_ai_core.agent_tool import AgentTool
from otter_ai_core.model import Model

from .types import QueuedUserMessage


def run_agent_loop(
    model: Model,
    tools: list[AgentTool],
    follow_up_queue: asyncio.Queue[QueuedUserMessage],
    steering_queue: asyncio.Queue[QueuedUserMessage],
) -> Awaitable[None]:
    raise NotImplementedError
