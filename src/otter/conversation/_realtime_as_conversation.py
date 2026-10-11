"""A realtime conversation used where a plain conversation is wanted."""

from collections.abc import Sequence
from contextlib import aclosing

from otter.domain.messages import AssistantMessage, UserPart
from otter.realtime_conversation import RealtimeConversation, TurnDone

from ._conversation import Conversation


def realtime_as_conversation(realtime: RealtimeConversation) -> Conversation:
    """Return a conversation that is `realtime`, its turns taken whole.

    What is added to it is added to `realtime`, and generating reads a turn of
    `realtime` through to its end and returns the whole of it: a turn the model spoke
    is returned as its transcript. Closing it closes `realtime`. Whatever `realtime`
    raises propagates.
    """
    return _RealtimeAsConversation(realtime)


class _RealtimeAsConversation:
    def __init__(self, realtime: RealtimeConversation) -> None:
        self._realtime = realtime

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        self._realtime.add_user_message(content)

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        self._realtime.add_tool_result(tool_call_id, text)

    async def aclose(self) -> None:
        await self._realtime.aclose()

    async def generate(self) -> AssistantMessage:
        async with aclosing(self._realtime.generate()) as events:
            async for event in events:
                if isinstance(event, TurnDone):
                    return event.message
        raise RuntimeError("the realtime conversation ended its turn without the turn")
