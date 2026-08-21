import pytest

from otter_ai_core.conversation import TextContent, UserMessage
from otter_ai_core.in_memory_session import InMemorySessionManager
from otter_ai_core.session import SESSION_MANAGER_CONTRACT_CHECKS, SessionManagerContractCheck


@pytest.mark.parametrize("check", SESSION_MANAGER_CONTRACT_CHECKS, ids=lambda c: c.__name__)
async def test_in_memory_manager_satisfies_session_contract(
    check: SessionManagerContractCheck,
) -> None:
    await check(lambda: InMemorySessionManager())


def _user_message(text: str) -> UserMessage:
    return UserMessage(id=f"user-{text}", content=[TextContent(text=text)])


async def test_entries_reflects_appended_messages_across_session_lifecycle() -> None:
    manager = InMemorySessionManager()
    assert manager.entries == ()
    first = _user_message("first")
    second = _user_message("second")
    async with manager:
        await manager.append_message(first)
        held = manager.entries
        assert held == (first,)
        await manager.append_message(second)
    assert held == (first,)
    assert list(manager.entries) == [first, second]
