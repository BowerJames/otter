"""Model-controller subpackage facade.

This package groups the high-level conversation driver built atop the
:mod:`otter_ai_core.model_connection` typed-connection layer:

* :class:`ModelController` — wraps a
  :data:`~otter_ai_core.model_connection.ModelConnectionClient`, drives the
  conversation (``add_messages`` / ``generate`` / ``abort``), tracks idle/busy
  state from inbound ``response.done`` events, and re-publishes every server
  event to a :class:`ModelBus`.
* :class:`ModelBus` — the model-event specialization of
  :class:`otter_ai_core.bus.Bus`, keyed on
  :class:`~otter_ai_core.model_connection.ServerContextEventType`, with its own
  worker task and per-handler error isolation.
* :class:`State` — the controller's mutable idle/busy latch and closing flag.

Unlike the lower-level :mod:`otter_ai_core.model_connection` (subpackage-only),
the controller is re-exported at the top level
(:data:`~otter_ai_core.ModelController` / :data:`~otter_ai_core.ModelBus` /
:data:`~otter_ai_core.State`) as the high-level convenience most callers want.
The public surface is declared via :data:`__all__`.
"""

from otter_ai_core.model_controller.bus import ModelBus
from otter_ai_core.model_controller.controller import ModelController
from otter_ai_core.model_controller.state import State
from otter_ai_core.model_controller.stream import create_model_controller_stream

__all__ = ["ModelController", "ModelBus", "State", "create_model_controller_stream"]
