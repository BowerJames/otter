from typing import Protocol


class Emitter(Protocol):
    async def emit(self, type: str, event: object) -> object: ...
