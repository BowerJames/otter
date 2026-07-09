from otter_ai_core.builder import BuilderFn
from otter_ai_core.connection import Connection, ConnectionFn

from .client_events import ClientEvent
from .server_events import ServerEvent

ModelConnection = Connection[ClientEvent, ServerEvent]
ModelConnectionFn = ConnectionFn[ClientEvent, ServerEvent]

type ModelConnectionFnBuilder[TOptions] = BuilderFn[TOptions, ModelConnectionFn]
