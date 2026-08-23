from typing import Protocol

from pydantic import BaseModel


class ToolSpec(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> type[BaseModel]: ...
