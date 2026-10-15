"""A model served over OpenAI's realtime endpoint."""

from .adapter import OpenAIRealtimeAdapter
from .connection import OpenAIConnect, RealtimeConnect, RealtimeConnection
from .errors import ModelFailed, TurnCutOff

__all__ = [
    "ModelFailed",
    "OpenAIConnect",
    "OpenAIRealtimeAdapter",
    "RealtimeConnect",
    "RealtimeConnection",
    "TurnCutOff",
]
