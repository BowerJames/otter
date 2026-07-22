"""Model-controller subpackage facade.

This package groups the high-level conversation driver built atop the
:mod:`otter_ai_core.model_connection` typed-connection layer:

* :class:`ModelController` — wraps a
  :data:`~otter_ai_core.model_connection.ModelConnectionClient`, drives the
  conversation (``add_message`` / ``generate`` / ``abort``), tracks idle/busy
  state from inbound ``response.done`` events, and re-publishes every server
  event to a descriptor-keyed :class:`otter_ai_core.bus.Bus`. Subscribe via the
  per-variant :class:`otter_ai_core.bus.BusEvent` descriptors in
  :mod:`otter_ai_core.model_controller.events` (``RESPONSE_DONE``, …).
* :class:`State` — the controller's mutable idle/busy latch and closing flag.
* :mod:`otter_ai_core.model_controller.events` — the
  :class:`~otter_ai_core.model_controller.events.ModelControllerEventTypes`
  enum and the typed :class:`~otter_ai_core.bus.BusEvent` descriptors the
  controller emits (re-exported here for convenience).

The commands are async and await a backend confirmation (an item-added echo
for :meth:`~otter_ai_core.ModelController.add_message`, a ``response.done``
for :meth:`~otter_ai_core.ModelController.generate`); see the controller module
docstring for the no-strand teardown guarantee.

Unlike the lower-level :mod:`otter_ai_core.model_connection` (subpackage-only),
the controller is re-exported at the top level
(:data:`~otter_ai_core.ModelController` / :data:`~otter_ai_core.State`) as the
high-level convenience most callers want. The public surface is declared via
:data:`__all__`.
"""

from otter_ai_core.model_controller.controller import ModelController
from otter_ai_core.model_controller.events import (
    BRANCH_MOVED,
    COMPACTION_DONE,
    RESPONSE_DONE,
    RESPONSE_STARTED,
    RESPONSE_UPDATED,
    TOOL_RESULT_ADDED,
    USER_ITEM_ADDED,
    USER_ITEM_UPDATED,
    ModelControllerEventTypes,
)
from otter_ai_core.model_controller.state import State
from otter_ai_core.model_controller.stream import create_model_controller_stream

__all__ = [
    "ModelController",
    "State",
    "create_model_controller_stream",
    # bus event surface
    "ModelControllerEventTypes",
    "RESPONSE_STARTED",
    "RESPONSE_UPDATED",
    "RESPONSE_DONE",
    "USER_ITEM_ADDED",
    "USER_ITEM_UPDATED",
    "TOOL_RESULT_ADDED",
    "COMPACTION_DONE",
    "BRANCH_MOVED",
]
