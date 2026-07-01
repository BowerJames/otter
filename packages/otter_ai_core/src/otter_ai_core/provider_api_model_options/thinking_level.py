from enum import StrEnum


class ThinkingLevel(StrEnum):
    """The union of the off switch and the five reasoning-effort levels.

    Mirrors pi-ai's ``ModelThinkingLevel``. ``Off`` means "do not send any
    reasoning field". The member values match the rungs of the clamp ladder
    used in
    :mod:`otter_ai_assistant_provider_stream.thinking`, one level up.
    """

    Off = "off"
    Minimal = "minimal"
    Low = "low"
    Medium = "medium"
    High = "high"
    XHigh = "xhigh"
