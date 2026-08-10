from __future__ import annotations

from typing import Protocol

from otter_ai_core.data_models.events import (
    ClientContextEvent,
    ServerContextEvent,
)

from ..capabilities.binary_state_machine import BinaryStateMachine
from ..capabilities.connection import Connection


class ModelConnection(
    Connection[ServerContextEvent, ClientContextEvent], BinaryStateMachine, Protocol
):
    pass


__all__ = [
    "ModelConnection",
]
