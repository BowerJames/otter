from enum import StrEnum


class KnownProviders(StrEnum):
    """The providers otter's dispatch layer ships built-in support for.

    Additional providers are registered at runtime by the dispatch layer, one
    level up. The member values flow onto inert ``AssistantMessage``
    provenance.
    """

    OPEN_AI = "openai"
    ZAI = "zai"
