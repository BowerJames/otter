from otter_ai_core.connection import Connection, ConnectionFn

from .client_events import ClientEvent
from .server_events import ServerEvent

ModelConnection = Connection[ClientEvent, ServerEvent]

type ModelConnectionFn[TOptions] = ConnectionFn[TOptions, ClientEvent, ServerEvent]
