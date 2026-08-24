from typing import Protocol


class AuthStorage(Protocol):
    """Abstraction over a store of API keys for model providers."""

    async def add_api_key(self, provider: str, api_key: str) -> None:
        """Stores the API key for the provider, replacing any key previously
        stored for it."""
        ...

    async def get_api_key(self, provider: str) -> str:
        """Returns the API key stored for the provider, exactly as it was
        added. Raises KeyError naming the provider when no key is stored for
        it."""
        ...
