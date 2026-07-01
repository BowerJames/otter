from enum import StrEnum


class KnownApis(StrEnum):
    """The api shapes otter's dispatch layer routes on.

    Member values are the string keys used by the provider/dispatch layer and
    flow onto inert ``AssistantMessage``/``Response*`` provenance. The
    ``chat-completions`` value matches
    :data:`otter_ai_chat_completions.ChatCompletionsApi` and the catalog; the
    ``realtime`` value matches
    :data:`otter_ai_realtime.RealtimeApi`.
    """

    ChatCompletion = "chat-completions"
    Responses = "responses"
    Realtime = "realtime"
