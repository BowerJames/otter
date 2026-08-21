from typing import Protocol


class AuthStorage(Protocol):
    async def add_api_key(self, provider: str, api_key: str) -> None: ...

    async def get_api_key(self, provider: str) -> str: ...
