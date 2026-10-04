"""The tools an agent can run on a model's behalf."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from otter.messages import ToolSpec


@dataclass(frozen=True)
class Tool:
    """A tool a model may ask for, and how it is run.

    `run` is given the arguments the model supplied and returns the text the model is
    shown as the result.
    """

    spec: ToolSpec
    run: Callable[[Mapping[str, object]], Awaitable[str]]
