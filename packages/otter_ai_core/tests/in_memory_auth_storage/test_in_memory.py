import pytest

from otter_ai_core.auth_storage import AUTH_STORAGE_CONTRACT_CHECKS, AuthStorageContractCheck
from otter_ai_core.in_memory_auth_storage import InMemoryAuthStorage


@pytest.mark.parametrize("check", AUTH_STORAGE_CONTRACT_CHECKS, ids=lambda c: c.__name__)
async def test_in_memory_auth_storage_satisfies_auth_storage_contract(
    check: AuthStorageContractCheck,
) -> None:
    await check(lambda: InMemoryAuthStorage())
