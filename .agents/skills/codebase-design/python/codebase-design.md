# Codebase Design in Python

The vocabulary in [SKILL.md](../SKILL.md) is language-agnostic. This file is its Python spelling.

## Vocabulary → Python

| Term | Python |
|---|---|
| **Interface** | for classes, a `typing.Protocol`; for functions, a type — `Callable[[Order], Receipt]` |
| **Port** | a parameter of the constructor, named for the dependency and typed by a `typing.Protocol` or a `Callable` type — `payments: Payments`, `clock: Clock` |
| **Adapter** | a class or function satisfying a port's or a contract's shape, taking the interfaces of the components it calls |
| **Decorator** | an adapter whose constructor takes the interface it satisfies — `LimitedPayments(inner: Payments)` |
| **Contract** | a `typing.Protocol` or a data carrier in the contracts package — `AgentTool`, `Currency` |
| **Foreign component** | a library, framework or runtime — `httpx`, the OpenAI SDK, FastAPI, Click, `logging`, Python running a file as `__main__` |
| **Outbound edge component** | a component whose constructor takes a library's own object — `StripePaymentsImpl(http: httpx.Client)` |
| **Inbound edge component** | a component whose interface is a framework's shape — a constructor returning a FastAPI `APIRouter`, a `logging.Handler` subclass |
| **View** | a `typing.Protocol` in an edge component's package, describing the part of a foreign interface it touches — needed only when the library has no test hook (`httpx` has one: `httpx.MockTransport`; a websocket connection has none) |
| **Entrypoint** | a file the outside world is pointed at — a `[project.scripts]` function, the `app` object `uvicorn` is given, a file run as `__main__` |
| **Constructor** | when the implementation is a class, its `__init__`; when the implementation is a function, the function that takes the ports and returns it |
| **Data carrier** | a frozen `dataclass`, or a type alias such as a `Literal` |
| **Error** | an `Exception` subclass |

A constructor and a factory are told apart by name. A class's constructor is the class itself (`OrderProcessorImpl`). A function constructor is named for what it returns (`orders_router`). A factory is `create_…` (`create_order_processor`).

## Component

Below illustrates an example of an `OrderProcessor` component in Python.

The interface of a component can be spelled as a `typing.Protocol` or as a type. Both of the below define the same interface; pick one.

```python
from typing import Protocol

class OrderProcessor(Protocol): # Interface for the component, as a Protocol
    def __call__(self, order: Order) -> Receipt: ...
```

```python
from typing import Callable

type OrderProcessor = Callable[[Order], Receipt] # Interface for the component, as a type
```

The rest of the component is the same whichever spelling is used. It has two dependencies, so it has two ports:

```python
from datetime import datetime
from typing import Callable, Protocol

from contracts.currency import Currency # A contract: Currency means the same thing to every component

class Payments(Protocol): # The interface of the payments port: only what the component calls
    def charge(self, amount: int, currency: Currency) -> bool: ...

type Clock = Callable[[], datetime] # The interface of the clock port

class PaymentDeclined(Exception): # An error the component's implementation determines, so the component owns it
    ...

class OrderProcessorImpl: # Implementation of the component
    def __init__(
        self,
        payments: Payments, # a port
        clock: Clock, # a port
        currency: Currency # configuration
    ): # Constructor for the component
        self.payments = payments
        self.clock = clock
        self.currency = currency

    def __call__(self, order: Order) -> Receipt:
        total = sum(item.cost for item in order.items)
        if not self.payments.charge(total, self.currency):
            raise PaymentDeclined(order.id)
        return Receipt(total=total, currency=self.currency, at=self.clock())
```

Each port is satisfied, swapped and faked on its own: a test can fix the clock without touching payments, and a new payment provider never touches the clock.

## Outbound edge component

`StripePayments` is a component of its own: it faces Stripe's HTTP API, a foreign component. Its constructor takes the library's own object, so a test can pass an `httpx.Client` on `httpx.MockTransport`:

```python
from typing import Protocol

import httpx

from contracts.currency import Currency

class StripePayments(Protocol): # Interface for the edge component
    def charge(self, amount: int, currency: Currency) -> bool: ...

class StripePaymentsImpl: # An outbound edge component
    def __init__(
        self,
        http: httpx.Client, # the library's own object: its foreign dependency
        api_key: str # configuration
    ):
        self.http = http
        self.api_key = api_key

    def charge(self, amount: int, currency: Currency) -> bool:
        response = self.http.post("/v1/charges", data=to_charge_form(amount, currency)) # humble shell
        return charged(response.status_code)

def to_charge_form(amount: int, currency: Currency) -> dict[str, str]: # translation: a plain function
    return {"amount": str(amount), "currency": currency.lower()}

def charged(status_code: int) -> bool:
    return status_code != 402
```

Its interface satisfies the `payments` port as it is, so a factory passes it straight to the port: there is no adapter. Matching is structural: anything with a matching `charge` satisfies `Payments`. The clock's port is satisfied by the standard library's own function, which already has its shape:

```python
from datetime import UTC, datetime
from functools import partial

def create_stripe_payments(api_key: str) -> StripePayments: # A factory for the edge component
    return StripePaymentsImpl(httpx.Client(base_url="https://api.stripe.com"), api_key)

def create_order_processor(api_key: str, currency: Currency) -> OrderProcessor: # A factory for the order processor
    return OrderProcessorImpl(
        payments=create_stripe_payments(api_key), # a component passed directly to a port
        clock=partial(datetime.now, UTC), # a foreign object that already has the port's shape
        currency=currency,
    )
```

Building an `httpx.Client` reaches no resource: it connects only when a request is sent. A factory passes every value a library would otherwise read from the environment, such as an API key, as a parameter.

## Decorator

A decorator wraps the interface it satisfies. `LimitedPayments` refuses any charge over a configured limit, and passes every other charge to the payments it wraps:

```python
class LimitedPayments(Payments): # A decorator for the payments port
    def __init__(self, inner: Payments, limit: int): # Takes the interface it satisfies
        self.inner = inner
        self.limit = limit

    def charge(self, amount: int, currency: Currency) -> bool:
        if amount > self.limit:
            return False
        return self.inner.charge(amount, currency)
```

A factory combines them at runtime: `LimitedPayments(create_stripe_payments(api_key), limit=10_000)`. Neither imports the other.

An adapter inherits from the interface it satisfies (`class LimitedPayments(Payments)`). The inheritance is a reminder, not a requirement: it links the adapter to the port it is intended for, so a developer reading the adapter can see the dependency.

## Inbound edge component

An `orders_router` is called by FastAPI, so its interface is foreign: the `APIRouter` FastAPI mounts. Its port is the project's own, and the translation between HTTP bodies and its data carriers is plain functions:

```python
from typing import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

type PlaceOrder = Callable[[NewOrder], Placed | None] # The interface of its port: None means the payment was declined

class OrderBody(BaseModel): # Part of the foreign interface: FastAPI reads requests through pydantic
    id: str
    costs: list[int]

class ReceiptBody(BaseModel):
    total: int
    currency: str

def orders_router(place_order: PlaceOrder) -> APIRouter: # Constructor: its interface is foreign
    router = APIRouter()

    @router.post("/orders", status_code=201)
    def create(body: OrderBody) -> ReceiptBody: # humble shell
        placed = place_order(to_new_order(body))
        if placed is None:
            raise HTTPException(status_code=402, detail="payment declined") # handled: 402 is the answer
        return to_body(placed)

    return router

def to_new_order(body: OrderBody) -> NewOrder: # translation: plain functions
    return NewOrder(id=body.id, costs=tuple(body.costs))

def to_body(placed: Placed) -> ReceiptBody:
    return ReceiptBody(total=placed.total, currency=placed.currency)
```

`NewOrder` and `Placed` are the router's own data carriers. The router never imports the order processor: an adapter satisfies `place_order` by calling it, translating its data carriers and handling its `PaymentDeclined` as `None`:

```python
class OrderProcessorAdapter: # adapters/orders_router/place_order/order_processor
    def __init__(self, order_processor: OrderProcessor): # Takes the interface of the component it calls
        self.order_processor = order_processor

    def __call__(self, new_order: NewOrder) -> Placed | None:
        order = Order(id=new_order.id, items=tuple(OrderItem(name=f"item_{i}", cost=c) for i, c in enumerate(new_order.costs)))
        try:
            receipt = self.order_processor(order)
        except PaymentDeclined:
            return None # handled: a decline is an answer the port can give
        return Placed(total=receipt.total, currency=receipt.currency)
```

The port arrives through the constructor, never through FastAPI's `Depends`. Building the router reaches no resource; mounting it on an app and serving it is the entrypoint's work. Mapping the decline to a 402 is handling: the router decides the outcome.

## A component that opens sessions

A realtime model holds a connection for the length of a conversation. The model opens sessions and stays stateless; the session holds the connection. The SDK's websocket connection has no test hook, so the edge component declares a view of the part it uses:

```python
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

class RealtimeConnection(Protocol): # A view: the part of the SDK's connection the component uses
    async def send(self, event: dict[str, Any]) -> None: ...
    async def recv(self) -> dict[str, Any]: ...

class Connect(Protocol): # A view of the SDK's client.realtime.connect
    def __call__(self, *, model: str) -> AbstractAsyncContextManager[RealtimeConnection]: ...

class RealtimeSession(Protocol): # The session's interface: every method is always valid
    async def send(self, event: ClientEvent) -> None: ...
    async def receive(self) -> ServerEvent: ...

class RealtimeModel(Protocol): # The component's interface: its lifecycle is part of it
    def connect(self) -> AbstractAsyncContextManager[RealtimeSession]: ...

class OpenAIRealtimeModel: # An outbound edge component
    def __init__(self, connect: Connect, model_name: str):
        self.open_connection = connect # reaches nothing
        self.model_name = model_name

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[RealtimeSession]:
        async with self.open_connection(model=self.model_name) as connection: # the resource, acquired when called
            yield OpenAIRealtimeSession(connection)
```

Its factory passes the SDK's own function, which satisfies the view by shape: `OpenAIRealtimeModel(AsyncOpenAI(api_key=api_key).realtime.connect, model_name)`.

Whoever owns the conversation opens it: `async with model.connect() as session:`.

## Errors

The edge component handles what it can decide and lets everything else propagate:

```python
class StripePaymentsImpl:
    def charge(self, amount: int, currency: Currency) -> bool:
        response = self.http.post(...) # a network error propagates unchanged
        if response.status_code == 402:
            return False # handled: a decline is an answer the interface can give
        return True
```

Wrapping hides the error's origin:

```python
    def charge(self, amount: int, currency: Currency) -> bool:
        try:
            response = self.http.post(...)
        except httpx.ConnectError as error:
            raise PaymentFailed() from error # bad: wraps an error the component did not determine
```
