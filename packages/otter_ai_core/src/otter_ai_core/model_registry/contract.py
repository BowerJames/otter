from collections.abc import Awaitable, Callable

from otter_ai_core.model import MODEL_CONTRACT_CHECKS

from .signature import Provider

# A ProviderFactory yields a fresh Provider. Checks arrange all state they
# need through the interface itself.
type ProviderFactory = Callable[[], Provider]
type ProviderContractCheck = Callable[[ProviderFactory], Awaitable[None]]


async def check_model_factory_satisfies_model_contract(
    make_provider: ProviderFactory,
) -> None:
    provider = make_provider()
    factory = provider.get_model_factory("some-model", "sk-test")
    first = factory("system prompt", [])
    second = factory("system prompt", [])
    async with first, second:
        await first.add_user_message("hello")
        message = await second.add_user_message("hello")
        assert message.content[0].text == "hello"
        await first.generate()
    for model_check in MODEL_CONTRACT_CHECKS:
        await model_check(factory)


PROVIDER_CONTRACT_CHECKS: list[ProviderContractCheck] = [
    check_model_factory_satisfies_model_contract,
]
