"""A model an agent session can run on, and how one is named and made."""

from collections.abc import Callable, Sequence
from typing import Protocol

from otter.auth_resolver import ApiKey, Provider
from otter.conversation import Conversation
from otter.messages import ToolSpec

type ModelName = str
"""The name a provider knows a model by, such as "glm-5.3"."""

type ModelType = str
"""How a model is spoken to, such as "chat-completions" or "responses"."""


class ModelConfig(Protocol):
    """Which model is meant: its name, how it is spoken to, and who serves it."""

    @property
    def model_name(self) -> ModelName: ...

    @property
    def model_type(self) -> ModelType: ...

    @property
    def provider(self) -> Provider: ...


type Model = Callable[[str | None, Sequence[ToolSpec]], Conversation]
"""Starts a new, empty conversation with the model.

It is given the system prompt the model sees ahead of every turn, or None for no system
prompt, and the tools the model may ask to have called.
"""

type ModelFactory = Callable[[ModelConfig, ApiKey], Model]
"""Makes the model a configuration names, to be reached with the given API key.

Raises `ValueError` for a configuration it cannot make a model for.
"""
