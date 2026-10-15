"""A model served over an OpenAI-compatible responses endpoint."""

from .adapter import OpenAIResponsesAdapter
from .errors import ModelFailed

__all__ = ["ModelFailed", "OpenAIResponsesAdapter"]
