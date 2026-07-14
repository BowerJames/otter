"""Model-connection subpackage facade.

This package groups the typed event protocol and the typed connection aliases
used to drive a model connection over an abortable two-way conduit:

* the :data:`ClientContextEvent` family (client→server / outbound) and the
  :data:`ServerContextEvent` family (server→client / inbound) — otter's
  general model-connection event structure, partly modelled on the OpenAI
  Responses / Realtime event families; and
* the typed aliases :data:`ModelConnectionClient`,
  :data:`ModelConnectionBackend`, and :data:`ModelConnectionPair`, which
  specialize the generic abortable-connection runtime in
  :mod:`otter_ai_core.connection` (itself layered over the bidirectional
  channel runtime in :mod:`otter_ai_core.bidirectional_channel`).

It is the bidirectional peer of :mod:`otter_ai_core.assistant_message_stream`,
and a supported import surface (Strategy A — two-layer facade): callers import
from :mod:`otter_ai_core.model_connection`. The public surface is declared via
:data:`__all__`.

No producer-side seam type is defined yet; a connection-level seam will be
added in a future dispatch package.
"""

from .client_context_events import (
    AddToolResultMessage,
    AddUserMessage,
    ClientContextEvent,
    CreateResponse,
)
from .model_connection import (
    ModelConnectionBackend,
    ModelConnectionClient,
    ModelConnectionPair,
)
from .server_context_events import (
    ResponseDelta,
    ResponseDone,
    ResponseStarted,
    ServerContextEvent,
    ToolResultAdded,
    UserItemAdded,
)

__all__ = [
    # typed aliases
    "ModelConnectionBackend",
    "ModelConnectionClient",
    "ModelConnectionPair",
    # client→server events
    "AddToolResultMessage",
    "AddUserMessage",
    "ClientContextEvent",
    "CreateResponse",
    # server→client events
    "ResponseDelta",
    "ResponseDone",
    "ResponseStarted",
    "ServerContextEvent",
    "ToolResultAdded",
    "UserItemAdded",
]
