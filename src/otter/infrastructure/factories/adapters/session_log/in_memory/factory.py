from otter.core.session_log import SessionLogPort
from otter.infrastructure.adapters.session_log.in_memory import InMemoryAdapter


def create_in_memory_adapter() -> SessionLogPort:
    """Return a session log's text, kept in memory."""
    return InMemoryAdapter()
