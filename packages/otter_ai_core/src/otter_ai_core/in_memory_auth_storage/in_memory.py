class InMemoryAuthStorage:
    def __init__(self) -> None:
        self._api_keys: dict[str, str] = {}

    async def add_api_key(self, provider: str, api_key: str) -> None:
        self._api_keys[provider] = api_key

    async def get_api_key(self, provider: str) -> str:
        if provider not in self._api_keys:
            raise KeyError(f"No API key stored for provider: {provider}")
        return self._api_keys[provider]
