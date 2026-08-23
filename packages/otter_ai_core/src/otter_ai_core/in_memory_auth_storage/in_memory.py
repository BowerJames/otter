class InMemoryAuthStorage:
    """An in-memory store of API keys: one key per provider, held in process
    memory for the store's lifetime."""

    def __init__(self) -> None:
        self._api_keys: dict[str, str] = {}

    async def add_api_key(self, provider: str, api_key: str) -> None:
        """Stores the API key for the provider, replacing any key previously
        stored for it."""
        self._api_keys[provider] = api_key

    async def get_api_key(self, provider: str) -> str:
        """Returns the API key stored for the provider, exactly as it was
        added. Raises KeyError naming the provider when no key is stored for
        it."""
        if provider not in self._api_keys:
            raise KeyError(f"No API key stored for provider: {provider}")
        return self._api_keys[provider]
