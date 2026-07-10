from otter_ai_core.bidirectional_channel import (
    BidirectionalChannel,
    BidirectionalChannelFn,
)
from otter_ai_core.builder import BuilderFn

from .client_events import ClientEvent
from .server_events import ServerEvent

ModelConnection = BidirectionalChannel[ClientEvent, ServerEvent]
ModelConnectionFn = BidirectionalChannelFn[ClientEvent, ServerEvent]

type ModelConnectionFnBuilder[TOptions] = BuilderFn[TOptions, ModelConnectionFn]
