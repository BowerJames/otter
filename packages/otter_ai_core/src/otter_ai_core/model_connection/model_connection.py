"""Typed connection aliases for a model connection.

This module fixes the two type parameters of the generic abortable-connection
runtime (:mod:`otter_ai_core.connection`) to otter's model-connection event
protocol:

* :data:`ModelConnectionClient` — the consumer handle: iterate
  :data:`~otter_ai_core.model_connection.ServerContextEvent` s, push
  :data:`~otter_ai_core.model_connection.ClientContextEvent` s, and abort via
  :meth:`~otter_ai_core.connection.ConnectionClient.abort`.
* :data:`ModelConnectionBackend` — the producer handle: push
  :data:`~otter_ai_core.model_connection.ServerContextEvent` s, drain
  :data:`~otter_ai_core.model_connection.ClientContextEvent` s, and observe
  :attr:`~otter_ai_core.connection.ConnectionBackend.abort_signal`.
* :data:`ModelConnectionPair` — the linked pair returned by an annotated
  :func:`~otter_ai_core.connection.create_connection`.

These specialize the generic abortable two-way facade, mirroring how
:mod:`otter_ai_core.assistant_message_stream` specializes the one-way
:mod:`otter_ai_core.stream` runtime.

No producer-side seam type is defined yet (no ``ModelConnectionFn`` /
``ModelConnectionFnBuilder``); a connection-level seam will be added in a
future dispatch package. Obtain a live connection with an annotated
:func:`~otter_ai_core.connection.create_connection`::

    pair: ModelConnectionPair = create_connection()
    client: ModelConnectionClient = pair.client
"""

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
