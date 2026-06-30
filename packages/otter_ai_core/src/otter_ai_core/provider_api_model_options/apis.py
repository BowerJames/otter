from enum import StrEnum


class KnownApis(StrEnum):
    ChatCompletion = "chat-completion"
    Responses = "responses"
    Realtime = "realtime"
