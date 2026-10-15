from collections.abc import Sequence

from otter.core.agent_session import AgentSessionPort
from otter.core.model import Model
from otter.core.session_log import SessionLog
from otter.infrastructure.adapters.agent_session.plugin_host import (
    AgentTool,
    Plugin,
    PluginHostAdapter,
)


def create_plugin_host_adapter(
    model: Model,
    log: SessionLog,
    *,
    system_prompt: str | None,
    tools: Sequence[AgentTool],
    plugins: Sequence[Plugin],
) -> AgentSessionPort:
    """Return the world of a session run on `model`, its context kept in `log`."""
    return PluginHostAdapter(model, log, system_prompt=system_prompt, tools=tools, plugins=plugins)
