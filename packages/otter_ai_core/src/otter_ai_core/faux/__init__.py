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
