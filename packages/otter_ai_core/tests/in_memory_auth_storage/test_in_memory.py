import pytest

from otter_ai_core.in_memory_auth_storage import InMemoryAuthStorage


async def test_add_then_get_round_trips_keys_verbatim() -> None:
    storage = InMemoryAuthStorage()
    await storage.add_api_key("provider-a", "sk-a-123 ")
    await storage.add_api_key("provider-b", "")
    assert await storage.get_api_key("provider-a") == "sk-a-123 "
    assert await storage.get_api_key("provider-b") == ""


async def test_missing_api_key_raises_key_error_naming_provider() -> None:
    storage = InMemoryAuthStorage()
    with pytest.raises(KeyError) as exc_info:
        await storage.get_api_key("openai")
    assert "openai" in str(exc_info.value)


async def test_missing_api_key_still_raises_after_other_adds() -> None:
    storage = InMemoryAuthStorage()
    await storage.add_api_key("anthropic", "sk-ant")
    with pytest.raises(KeyError) as exc_info:
        await storage.get_api_key("openai")
    assert "openai" in str(exc_info.value)


async def test_overwrite_returns_latest_key() -> None:
    storage = InMemoryAuthStorage()
    await storage.add_api_key("openai", "sk-first")
    await storage.add_api_key("openai", "sk-second")
    assert await storage.get_api_key("openai") == "sk-second"
    await storage.add_api_key("openai", "sk-third")
    assert await storage.get_api_key("openai") == "sk-third"
