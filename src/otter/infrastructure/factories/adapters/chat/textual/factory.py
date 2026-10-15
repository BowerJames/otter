from otter.core.agent_session import AgentSession
from otter.core.chat import ChatPort
from otter.infrastructure.adapters.chat.textual import TextualAdapter, this_terminal


def create_textual_adapter(session: AgentSession, title: str) -> ChatPort:
    """Return `session`, held on a screen drawn under `title` on this process's terminal."""
    return TextualAdapter(session, title, this_terminal)
