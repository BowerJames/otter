"""A conversation with a model, and the providers one can be had with."""

from ._conversation import Conversation, ConversationFactory
from ._openai_chat_completions import create_openai_conversations
from ._openai_chat_completions_compatible import (
    create_openai_chat_completions_compatible_conversation,
)
from ._openai_responses import create_openai_responses_conversations
from ._openai_responses_compatible import create_openai_responses_compatible_conversation
from ._realtime_as_conversation import realtime_as_conversation
from ._zai_chat_completions import create_zai_coding_plan_conversations
from ._zai_responses import create_zai_coding_plan_responses_conversations

__all__ = [
    "Conversation",
    "ConversationFactory",
    "create_openai_chat_completions_compatible_conversation",
    "create_openai_conversations",
    "create_openai_responses_compatible_conversation",
    "create_openai_responses_conversations",
    "create_zai_coding_plan_conversations",
    "create_zai_coding_plan_responses_conversations",
    "realtime_as_conversation",
]
