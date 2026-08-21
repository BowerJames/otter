import pytest

from otter_ai_core.session import SESSION_MANAGER_CONTRACT_CHECKS, SessionManagerContractCheck
from otter_ai_core.session.in_memory import InMemorySessionManager


@pytest.mark.parametrize("check", SESSION_MANAGER_CONTRACT_CHECKS, ids=lambda c: c.__name__)
async def test_in_memory_manager_satisfies_session_contract(
    check: SessionManagerContractCheck,
) -> None:
    await check(lambda: InMemorySessionManager())
