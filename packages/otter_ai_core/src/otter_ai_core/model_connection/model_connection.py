from otter_ai_core.bidirectional_stream import (
    BidirectionalStream,
    BidirectionalStreamFn,
)
from otter_ai_core.builder import BuilderFn

from .client_events import ClientEvent
from .server_events import ServerEvent

ModelConnection = BidirectionalStream[ClientEvent, ServerEvent]
ModelConnectionFn = BidirectionalStreamFn[ClientEvent, ServerEvent]

type ModelConnectionFnBuilder[TOptions] = BuilderFn[TOptions, ModelConnectionFn]
