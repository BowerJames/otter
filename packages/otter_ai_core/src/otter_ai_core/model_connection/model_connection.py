from __future__ import annotations

from otter_ai_core.connection import (
    ConnectionBackend,
    ConnectionClient,
    ConnectionPair,
)

from .client_context_events import ClientContextEvent
from .server_context_events import ServerContextEvent

#: Connection of model-connection events. The consumer iterates server events,
#: pushes client events, and aborts.
ModelConnectionClient = ConnectionClient[ClientContextEvent, ServerContextEvent]

#: Producer handle for a :data:`ModelConnectionClient`. Pushes server events,
#: drains client events, and observes the shared abort signal.
ModelConnectionBackend = ConnectionBackend[ClientContextEvent, ServerContextEvent]

#: A linked :data:`ModelConnectionClient` / :data:`ModelConnectionBackend` pair
#: from :func:`~otter_ai_core.connection.create_connection`.
ModelConnectionPair = ConnectionPair[ClientContextEvent, ServerContextEvent]
