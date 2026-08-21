from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from .signature import AuthStorage

# An AuthStorageFactory yields a fresh, empty storage. Checks arrange all
# state they need through the interface itself.
type AuthStorageFactory = Callable[[], AuthStorage]
type AuthStorageContractCheck = Callable[[AuthStorageFactory], Awaitable[None]]


@contextmanager
def _raises_missing_api_key(provider: str) -> Iterator[None]:
    try:
        yield
    except KeyError as exc:
        assert provider in str(exc)
        return
    raise AssertionError("expected KeyError, none was raised")


async def check_add_then_get_round_trip(make_storage: AuthStorageFactory) -> None:
    storage = make_storage()
    await storage.add_api_key("provider-a", "sk-a-123 ")
    await storage.add_api_key("provider-b", "")
    assert await storage.get_api_key("provider-a") == "sk-a-123 "
    assert await storage.get_api_key("provider-b") == ""
    with _raises_missing_api_key("provider-c"):
        await storage.get_api_key("provider-c")


async def check_missing_api_key_error_names_provider(
    make_storage: AuthStorageFactory,
) -> None:
    storage = make_storage()
    with _raises_missing_api_key("openai"):
        await storage.get_api_key("openai")
    await storage.add_api_key("anthropic", "sk-ant")
    with _raises_missing_api_key("openai"):
        await storage.get_api_key("openai")


async def check_overwrite_returns_latest_key(make_storage: AuthStorageFactory) -> None:
    storage = make_storage()
    await storage.add_api_key("openai", "sk-first")
    await storage.add_api_key("openai", "sk-second")
    assert await storage.get_api_key("openai") == "sk-second"
    await storage.add_api_key("openai", "sk-third")
    assert await storage.get_api_key("openai") == "sk-third"


AUTH_STORAGE_CONTRACT_CHECKS: list[AuthStorageContractCheck] = [
    check_add_then_get_round_trip,
    check_missing_api_key_error_names_provider,
    check_overwrite_returns_latest_key,
]
