from typing import Protocol

from pydantic import BaseModel


class ToolSpec(Protocol):
    """Abstraction over the description of a tool's calling surface: the
    name, natural-language description, and argument schema needed to call
    the tool."""

    @property
    def name(self) -> str:
        """Stable identifier for the tool."""
        ...

    @property
    def description(self) -> str:
        """Natural-language account of what the tool does."""
        ...

    @property
    def parameters(self) -> type[BaseModel]:
        """Pydantic model describing the arguments the tool accepts."""
        ...
