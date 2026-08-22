from collections.abc import Awaitable, Callable

from ..model import MODEL_CONTRACT_CHECKS
from ..model.contract import _raises_runtime_error
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
    for model_check in MODEL_CONTRACT_CHECKS:
        await model_check(lambda: factory("system prompt", []))


async def check_factory_yields_fresh_models(make_provider: ProviderFactory) -> None:
    provider = make_provider()
    factory = provider.get_model_factory("some-model", "sk-test")
    first = factory("system prompt", [])
    second = factory("system prompt", [])

    async with first, second:
        await second.add_user_message("hello")
        await first.generate()

    with _raises_runtime_error():
        await first.add_user_message("hello")


PROVIDER_CONTRACT_CHECKS: list[ProviderContractCheck] = [
    check_model_factory_satisfies_model_contract,
    check_factory_yields_fresh_models,
]
