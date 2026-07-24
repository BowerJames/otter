"""Faux model-connection producer subpackage (integration-test harness).

This package ships a concrete, in-process, **deterministic, API-key-free**
model-connection producer (:class:`FauxModelProducer`) that pumps a
real :data:`~otter_ai_core.model_connection.ModelConnectionBackend` with
scriptable, protocol-conformant
:data:`~otter_ai_core.model_connection.ServerContextEvent` sequences. It is a
**test double, not a provider**: no inference, no network, no transport, no
registry — a concrete producer over the *existing* backend.

The one-call entry point :func:`create_faux_model` wires a real
:class:`~otter_ai_core.model_controller.ModelController` over a real
:func:`~otter_ai_core.connection.create_connection` pair driven by the faux
producer, so a downstream package can write true end-to-end integration tests
of the connection → controller → agent-loop stack with no API keys and no
flakiness.

It is a supported import surface (Strategy A — two-layer facade): import from
:mod:`otter_ai_core` (the headline API) or directly from
:mod:`otter_ai_core.faux`. The public surface is declared via :data:`__all__`.
"""

from __future__ import annotations

from otter_ai_core.faux.producer import FauxModel, FauxModelProducer, create_faux_model
from otter_ai_core.faux.script import (
    ClockFactory,
    FauxBranchOutcome,
    FauxCompactionOutcome,
    FauxModelScript,
    FauxProvenance,
    FauxResponse,
    FauxResponseRepeat,
    FauxStreamPolicy,
    ItemIdFactory,
    deterministic_clock,
    faux_text,
    faux_text_response,
    faux_tool_call_response,
    faux_usage,
    monotonic_item_ids,
    real_clock,
)

__all__ = [
    # producer + harness
    "FauxModelProducer",
    "FauxModel",
    "create_faux_model",
    # script model
    "FauxModelScript",
    "FauxResponse",
    "FauxResponseRepeat",
    "FauxStreamPolicy",
    "FauxProvenance",
    "FauxCompactionOutcome",
    "FauxBranchOutcome",
    # builders / factories
    "faux_text",
    "faux_text_response",
    "faux_tool_call_response",
    "faux_usage",
    "monotonic_item_ids",
    "deterministic_clock",
    "real_clock",
    # readability aliases
    "ItemIdFactory",
    "ClockFactory",
]
