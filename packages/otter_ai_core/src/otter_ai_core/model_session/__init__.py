"""Model-session subpackage facade.

This package groups the reactive, transport-agnostic layer that wraps a
:class:`~otter_ai_core.model_connection.ModelConnection`:

* :class:`ModelSession` — owns an inbound pump that reduces raw
  :data:`~otter_ai_core.model_connection.ServerEvent`\\ s to reduced
  :data:`SessionEvent`\\ s (via :func:`reduce_server_event`) and fans them out
  on a :class:`ModelSessionBus`; owns an :class:`ModelStateMachine`
  (``IDLE`` / ``WORKING`` / ``ABORTING``); and exposes the imperative commands
  (``create_response`` / ``add_context_item`` / ``abort_response`` / ``close``);
* the :data:`SessionEvent` family + :class:`SessionEventTypes` discriminator;
* :class:`ModelSessionBus` — the typed fan-out the session publishes to; and
* :class:`Phase` / :class:`ModelStateMachine` — the session's phase state.

It is tool-agnostic by design: it observes model responses only and does not
execute tools. The richer *turn* / *tool-execution* vocabulary belongs to the
agent layer above (see the ``otter_ai_agent`` package).

It is a supported import surface: callers may import from
``otter_ai_core.model_session``. The public surface is declared via
:data:`__all__`.
"""

from .bus import ModelSessionBus
from .events import (
    ContextItemAddedEvent,
    HandlerErrorEvent,
    ResponseAbortedEvent,
    ResponseDeltaEvent,
    ResponseDoneEvent,
    ResponseErrorEvent,
    ResponseStartedEvent,
    SessionClosedEvent,
    SessionErrorEvent,
    SessionEvent,
    SessionEventTypes,
)
from .model_session import ModelSession
from .phase import Phase
from .reduce import reduce_server_event
from .state_machine import ModelStateMachine

__all__ = [
    # session
    "ModelSession",
    "ModelSessionBus",
    # phase / state machine
    "Phase",
    "ModelStateMachine",
    # reduce
    "reduce_server_event",
    # events
    "SessionEvent",
    "SessionEventTypes",
    "ResponseStartedEvent",
    "ResponseDeltaEvent",
    "ResponseDoneEvent",
    "ResponseErrorEvent",
    "ResponseAbortedEvent",
    "ContextItemAddedEvent",
    "SessionErrorEvent",
    "SessionClosedEvent",
    "HandlerErrorEvent",
]
