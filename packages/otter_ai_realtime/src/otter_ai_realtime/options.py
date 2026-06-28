"""The seam's first argument: model + session config + runtime handles."""

from __future__ import annotations

from dataclasses import dataclass, field

from otter_ai_realtime.hooks import RealtimeHooks
from otter_ai_realtime.models import RealtimeModel, RealtimeSessionConfig


@dataclass
class RealtimeModelOptions:
    """Bundle passed to the connection function.

    Combines the pure-data :class:`RealtimeModel` with the per-session
    :class:`RealtimeSessionConfig` and runtime handles (hooks) that cannot
    live on a serializable Pydantic model. This bundle is the seam's first
    argument; the connection function is a value of
    ``ModelConnectionFn[RealtimeModelOptions]``. This bundle realises
    :data:`otter_ai_core.model_connection.ModelConnectionFn`'s ``TOptions``.

    The connection-cancel signal is **not** part of this bundle: it is
    supplied as the seam's third argument (an :class:`asyncio.Event`) and is
    the single source of truth for cooperative cancellation of the whole
    connection. Per-response abort is driven by the caller pushing an
    :class:`otter_ai_core.model_connection.AbortResponseEvent` onto the
    connection's outbound stream. The defaults let a "no session config, no
    hooks" caller construct this with just the model.
    """

    model: RealtimeModel
    session_config: RealtimeSessionConfig = field(default_factory=RealtimeSessionConfig)
    hooks: RealtimeHooks = field(default_factory=RealtimeHooks)
