from collections.abc import Sequence

from otter.core.agent_session import AgentSession, AgentSessionImpl
from otter.core.model import Model
from otter.core.session_log import SessionLog
from otter.infrastructure.factories.adapters.agent_session.plugin_host import (
    AgentTool,
    Plugin,
    create_plugin_host_adapter,
)
from otter.infrastructure.factories.modules.session_log import create_in_memory_session_log


def create_agent_session(
    model: Model,
    *,
    system_prompt: str | None = None,
    tools: Sequence[AgentTool] = (),
    plugins: Sequence[Plugin] = (),
    session_log: SessionLog | None = None,
) -> AgentSession:
    """Return an agent session run on `model`.

    `system_prompt` is what the model sees ahead of every turn, and `tools` are what it
    may ask to have run. Use the session in `async with`, and stream it inside: entering
    opens the model, and leaving closes it.

    `plugins` are asked at each of their hooks, in the order given (see `Plugin`). Make
    them for this session alone: a plugin holds one session's state.

    `session_log` is where the session's context is kept. The session starts out with
    the entries it holds, picking up where they leave off, and appends to it everything
    that then joins the conversation; leave it out for a session that starts with no
    context and keeps its own in memory.
    """
    log = session_log if session_log is not None else create_in_memory_session_log()
    return AgentSessionImpl(
        create_plugin_host_adapter(
            model, log, system_prompt=system_prompt, tools=tools, plugins=plugins
        )
    )
