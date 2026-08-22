import pytest

from otter_ai_core.fake_model import FakeModel
from otter_ai_core.in_memory_auth_storage import InMemoryAuthStorage
from otter_ai_core.model_registry import ModelRegistry
from otter_ai_core.model_registry.provider import (
    PROVIDER_CONTRACT_CHECKS,
    ProviderContractCheck,
)

from .fake_provider import FakeProvider


async def _storage_seeded_with(*entries: tuple[str, str]) -> InMemoryAuthStorage:
    storage = InMemoryAuthStorage()
    for provider, api_key in entries:
        await storage.add_api_key(provider, api_key)
    return storage


@pytest.mark.parametrize("check", PROVIDER_CONTRACT_CHECKS, ids=lambda c: c.__name__)
async def test_fake_provider_satisfies_provider_contract(
    check: ProviderContractCheck,
) -> None:
    await check(FakeProvider)


async def test_get_model_factory_resolves_provider_model_and_api_key() -> None:
    provider = FakeProvider()
    provider.set_returned_factory(lambda system_prompt, tools: FakeModel([]))
    registry = ModelRegistry({"openai": provider}, await _storage_seeded_with(("openai", "sk-key")))

    factory = await registry.get_model_factory("openai", "gpt-4o")

    assert provider.received == ("gpt-4o", "sk-key")
    assert factory is provider.returned_factory


async def test_unknown_provider_raises_key_error_naming_provider() -> None:
    provider = FakeProvider()
    registry = ModelRegistry({"openai": provider}, await _storage_seeded_with(("openai", "sk-key")))

    with pytest.raises(KeyError) as exc_info:
        await registry.get_model_factory("anthropic", "claude-sonnet-4")

    assert "anthropic" in str(exc_info.value)
    assert provider.received is None


async def test_unknown_model_raises_key_error_naming_provider_and_model() -> None:
    provider = FakeProvider(known_models={"gpt-4o"})
    registry = ModelRegistry({"openai": provider}, await _storage_seeded_with(("openai", "sk-key")))

    with pytest.raises(KeyError) as exc_info:
        await registry.get_model_factory("openai", "o3")

    assert "openai/o3" in str(exc_info.value)


async def test_missing_api_key_propagates_key_error_from_auth_storage() -> None:
    provider = FakeProvider()
    registry = ModelRegistry({"openai": provider}, InMemoryAuthStorage())

    with pytest.raises(KeyError) as exc_info:
        await registry.get_model_factory("openai", "gpt-4o")

    assert "openai" in str(exc_info.value)
    assert provider.received is None


async def test_factories_for_distinct_providers_are_resolved_independently() -> None:
    openai = FakeProvider(known_models={"gpt-4o"})
    anthropic = FakeProvider(known_models={"claude-sonnet-4"})
    openai.set_returned_factory(lambda system_prompt, tools: FakeModel([]))
    anthropic.set_returned_factory(lambda system_prompt, tools: FakeModel([]))
    registry = ModelRegistry(
        {"openai": openai, "anthropic": anthropic},
        await _storage_seeded_with(("openai", "sk-openai"), ("anthropic", "sk-ant")),
    )

    assert await registry.get_model_factory("openai", "gpt-4o") is openai.returned_factory
    assert (
        await registry.get_model_factory("anthropic", "claude-sonnet-4")
        is anthropic.returned_factory
    )
    assert openai.received == ("gpt-4o", "sk-openai")
    assert anthropic.received == ("claude-sonnet-4", "sk-ant")
