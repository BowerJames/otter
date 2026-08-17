import pytest
from pydantic import ValidationError

from otter_ai_core.agent_loop import AgentLoopOptions


def test_max_generations_must_be_at_least_one() -> None:
    AgentLoopOptions(max_generations=1)
    with pytest.raises(ValidationError):
        AgentLoopOptions(max_generations=0)
