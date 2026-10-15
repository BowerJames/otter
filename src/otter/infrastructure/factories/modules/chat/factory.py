from otter.core.agent_session import AgentSession
from otter.core.chat import Chat, ChatImpl
from otter.infrastructure.factories.adapters.chat.textual import create_textual_adapter


def create_terminal_chat(session: AgentSession, title: str) -> Chat:
    """Return a chat with `session`, drawn under `title` on this process's terminal.

    Textual draws it: install otter with its `tui` extra.
    """
    return ChatImpl(create_textual_adapter(session, title))
