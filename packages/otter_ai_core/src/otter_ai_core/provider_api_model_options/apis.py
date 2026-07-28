from enum import StrEnum


class KnownApis(StrEnum):
    ChatCompletion = "chat-completions"
    Responses = "responses"
    Realtime = "realtime"
