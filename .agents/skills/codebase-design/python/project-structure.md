# Project Structure in Python

The rules in [project-structure.md](../project-structure.md) are language-agnostic. This file is their Python spelling.

## Vocabulary → Python

| Term | Python |
|---|---|
| **Package** | a directory with an `__init__.py` |
| **Export file** | the package's `__init__.py`, re-exporting names and listing them in `__all__` |
| **Data carrier** | a frozen `dataclass`, or a type alias such as a `Literal` |
| **Contracts package** | `contracts`, with one file per concept — `contracts/currency.py`, `contracts/agent_tool.py` |
| **Contract** | a `typing.Protocol` or a data carrier in its own file in `contracts` — `AgentTool` in `contracts/agent_tool.py` |
| **Factory package** | `factories/components/<component_name>` or `factories/adapters/…`, with the factories in `factory.py`, and a composite in a file named for it |
| **Entrypoint** | a file in `entrypoints` — `entrypoints/cli.py` named in `[project.scripts]`, `entrypoints/fastapi.py` whose `app` uvicorn is given |
| **Inbound edge component** | a component whose constructor returns a framework's object — `orders_router` returning an `APIRouter` |
| **Outbound edge component** | a component whose constructor takes a library's object — `StripePaymentsImpl` taking an `httpx.Client` |

The examples use `shop` as the project's package, so every path below sits under `src/shop`, and every import starts `shop.`.

Python calls every `.py` file a "module". This skill says "file" for a `.py` file, and "component" for a package in `components`.

Files behind the export file carry no `_` prefix. The export file decides what is public: a name is public if `__init__.py` re-exports it and lists it in `__all__`, and private otherwise.

## Example 1: a component and its ports

An `OrderProcessor` component charges for an order through its `payments` port, and stamps the receipt through its `clock` port.

```
src/shop/
  contracts/
    __init__.py
    currency.py                # Currency
  components/
    order_processor/
      __init__.py              # the export file
      interface.py             # OrderProcessor
      ports.py                 # Payments, Clock
      data.py                  # Order, OrderItem, Receipt
      errors.py                # PaymentDeclined
      implementation.py        # OrderProcessorImpl; could be several files
```

`Currency` was promoted to the contracts package when a second component needed it and it meant the same thing to both. `Order` and `Receipt` appear in the `OrderProcessor` interface, so they are in the component's data file:

```python
# contracts/currency.py
from typing import Literal

type Currency = Literal["GBP", "USD", "EUR"]
```

```python
# components/order_processor/data.py
from dataclasses import dataclass
from datetime import datetime

from shop.contracts.currency import Currency

@dataclass(frozen=True)
class OrderItem:
    name: str
    cost: int # in the currency's minor unit

@dataclass(frozen=True)
class Order:
    id: str
    items: tuple[OrderItem, ...]

@dataclass(frozen=True)
class Receipt:
    total: int
    currency: Currency
    at: datetime
```

The interface, the ports, the errors and the implementation each have their own file:

```python
# components/order_processor/interface.py
from typing import Protocol

from .data import Order, Receipt

class OrderProcessor(Protocol): # Interface for the component
    def __call__(self, order: Order) -> Receipt: ...
```

```python
# components/order_processor/ports.py
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from shop.contracts.currency import Currency

class Payments(Protocol): # The interface of the payments port
    def charge(self, amount: int, currency: Currency) -> bool: ...

type Clock = Callable[[], datetime] # The interface of the clock port
```

```python
# components/order_processor/errors.py
class PaymentDeclined(Exception): # Determined by the component's implementation
    ...
```

```python
# components/order_processor/implementation.py
from shop.contracts.currency import Currency

from .data import Order, Receipt
from .errors import PaymentDeclined
from .ports import Clock, Payments

class OrderProcessorImpl: # Implementation of the component
    def __init__(
        self,
        payments: Payments,
        clock: Clock,
        currency: Currency
    ): # Constructor for the component
        self.payments = payments
        self.clock = clock
        self.currency = currency

    def __call__(self, order: Order) -> Receipt:
        ...
```

```python
# components/order_processor/__init__.py
from .data import Order, OrderItem, Receipt
from .errors import PaymentDeclined
from .implementation import OrderProcessorImpl
from .interface import OrderProcessor
from .ports import Clock, Payments

__all__ = [
    "Clock",
    "Order",
    "OrderItem",
    "OrderProcessor",
    "OrderProcessorImpl",
    "Payments",
    "PaymentDeclined",
    "Receipt",
]
```

A component imports nothing from another component, an adapter or a factory:

```python
# components/order_processor/implementation.py
from shop.components.stripe_payments import StripePaymentsImpl   # bad: a component importing another component
from shop.factories.components.stripe_payments import ...         # bad: a component importing a factory
```

## Example 2: an outbound edge component and its factory

`StripePayments` faces Stripe's HTTP API. It is the only package in the project that knows Stripe's request format:

```
src/shop/
  components/
    stripe_payments/
      __init__.py              # the export file
      interface.py             # StripePayments
      implementation.py        # StripePaymentsImpl: the humble shell, taking an httpx.Client
      translate.py             # to_charge_form, charged: plain functions
  factories/
    components/
      order_processor/
        __init__.py
        factory.py             # create_order_processor
      stripe_payments/
        __init__.py
        factory.py             # create_stripe_payments
```

```python
# components/stripe_payments/implementation.py
import httpx                                                     # good: the library whose client it takes

from shop.contracts.currency import Currency

from .translate import charged, to_charge_form

class StripePaymentsImpl: # An outbound edge component
    def __init__(self, http: httpx.Client, api_key: str): # Constructor: takes the library's own client
        self.http = http
        self.api_key = api_key

    def charge(self, amount: int, currency: Currency) -> bool: # the humble shell
        response = self.http.post("/v1/charges", data=to_charge_form(amount, currency), auth=(self.api_key, ""))
        return charged(response.status_code)
```

Its factory builds the library object, and returns the interface:

```python
# factories/components/stripe_payments/factory.py
import httpx

from shop.components.stripe_payments import StripePayments, StripePaymentsImpl

def create_stripe_payments(api_key: str) -> StripePayments:
    return StripePaymentsImpl(httpx.Client(base_url="https://api.stripe.com"), api_key) # Building reaches no resource
```

`StripePayments` satisfies the order processor's `payments` port as it is, so the order processor's factory passes it straight to the port. There is no adapter:

```python
# factories/components/order_processor/factory.py
from datetime import UTC, datetime
from functools import partial

from shop.components.order_processor import OrderProcessor, OrderProcessorImpl
from shop.contracts.currency import Currency
from shop.factories.components.stripe_payments import create_stripe_payments

def create_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    return OrderProcessorImpl(
        payments=create_stripe_payments(api_key),
        clock=partial(datetime.now, UTC),
        currency=currency,
    )
```

## Example 3: an adapter joining two components

A `Checkout` component is built on top of order processing. It does not import `components/order_processor`. It declares its own data carriers and a `payment` port with the shape it needs:

```python
# components/checkout/data.py
from dataclasses import dataclass

@dataclass(frozen=True)
class CartLine:
    product: str
    price: int

@dataclass(frozen=True)
class Cart:
    id: str
    lines: tuple[CartLine, ...]
```

```python
# components/checkout/ports.py
from typing import Protocol

from .data import Cart

class Payment(Protocol): # The interface of checkout's payment port
    def pay(self, cart: Cart) -> int: ...
```

The order processor's interface does not satisfy that port as it is, so an adapter under `adapters/checkout/payment` satisfies it by calling the order processor, translating between the two components' data carriers:

```python
# adapters/checkout/payment/order_processor/adapter.py
from shop.components.checkout import Cart, Payment
from shop.components.order_processor import Order, OrderItem, OrderProcessor

class OrderProcessorAdapter(Payment): # Adapter joining checkout to the order processor
    def __init__(self, order_processor: OrderProcessor): # Takes the interface of the component it calls
        self.order_processor = order_processor

    def pay(self, cart: Cart) -> int:
        order = Order(
            id=cart.id,
            items=tuple(OrderItem(name=line.product, cost=line.price) for line in cart.lines)
        ) # checkout's data, translated into the order processor's
        return self.order_processor(order).total
```

```python
# adapters/checkout/payment/order_processor/__init__.py
from .adapter import OrderProcessorAdapter

__all__ = ["OrderProcessorAdapter"]
```

Its factory lives at the same path under `factories/adapters`, and the checkout's factory uses it:

```python
# factories/adapters/checkout/payment/order_processor/factory.py
from shop.adapters.checkout.payment.order_processor import OrderProcessorAdapter
from shop.components.checkout import Payment
from shop.components.order_processor import OrderProcessor

def create_order_processor_payment(order_processor: OrderProcessor) -> Payment: # Returns the port's interface
    return OrderProcessorAdapter(order_processor)
```

```python
# factories/components/checkout/factory.py
from shop.components.checkout import Checkout, CheckoutImpl
from shop.factories.adapters.checkout.payment.order_processor import create_order_processor_payment
from shop.factories.components.order_processor import create_order_processor

def create_checkout(api_key: str) -> Checkout:
    return CheckoutImpl(payment=create_order_processor_payment(create_order_processor(api_key, "GBP")))
```

An adapter imports only from the export files of the components it joins:

```python
# adapters/checkout/payment/order_processor/adapter.py
from shop.components.order_processor.interface import OrderProcessor      # bad: reaches behind the export file
from shop.components.order_processor import OrderProcessorImpl            # bad: an adapter importing a constructor
from shop.adapters.checkout.payment.retrying import RetryingPayment       # bad: an adapter importing another adapter
import httpx                                                              # bad: reaching a resource is an edge component's work
```

## Example 4: inbound edge components and their entrypoints

The program is started two ways: from the command line, and as a web server. Each way has an inbound edge component that its framework calls, and an entrypoint that starts it:

```
src/shop/
  components/
    orders_cli/
      __init__.py
      ports.py                 # PlaceOrder
      data.py                  # NewOrder, Placed
      implementation.py        # orders_cli: a Click command
    orders_router/
      __init__.py
      ports.py                 # PlaceOrder
      data.py                  # NewOrder, Placed
      bodies.py                # OrderBody, ReceiptBody: pydantic, part of the foreign interface
      implementation.py        # orders_router: returns an APIRouter
  adapters/
    orders_cli/
      place_order/
        order_processor/       # OrderProcessorAdapter
    orders_router/
      place_order/
        order_processor/       # OrderProcessorAdapter
  entrypoints/
    cli.py
    fastapi.py
```

Neither has an interface file: its interface is the framework's. Its port is the project's own:

```python
# components/orders_cli/implementation.py
import click

from .data import NewOrder
from .ports import PlaceOrder

def orders_cli(place_order: PlaceOrder) -> click.Command: # Constructor: returns the shape Click runs
    @click.command()
    @click.argument("order_id")
    @click.argument("costs", type=int, nargs=-1)
    def place(order_id: str, costs: tuple[int, ...]) -> None: # the humble shell
        placed = place_order(NewOrder(id=order_id, costs=costs))
        if placed is None:
            raise click.ClickException("payment declined") # handled: a failed exit is the answer
        click.echo(f"total={placed.total} {placed.currency}")

    return place
```

The two components each declare `PlaceOrder` and their own data carriers. They have the same shape, so promoting them to the contracts package is worth considering, but only if they mean the same thing to both. Until then, each has its own adapter to the order processor.

Each entrypoint reads the environment, builds the assembly through factories, registers the inbound edge component with its framework, and starts it:

```python
# entrypoints/cli.py
import os

from shop.factories.components.orders_cli import create_orders_cli

def main() -> None: # [project.scripts] shop = "shop.entrypoints.cli:main"
    cli = create_orders_cli(api_key=os.environ["STRIPE_API_KEY"], currency="GBP")
    cli() # starts Click
```

```python
# entrypoints/fastapi.py
import os

from fastapi import FastAPI

from shop.factories.components.orders_router import create_orders_router

app = FastAPI() # uvicorn runs shop.entrypoints.fastapi:app
app.include_router(create_orders_router(api_key=os.environ["STRIPE_API_KEY"], currency="GBP"))
```

The factory of an inbound edge component returns its foreign interface:

```python
# factories/components/orders_router/factory.py
from fastapi import APIRouter

from shop.components.orders_router import orders_router
from shop.contracts.currency import Currency
from shop.factories.adapters.orders_router.place_order.order_processor import create_order_processor_place_order
from shop.factories.components.order_processor import create_order_processor

def create_orders_router(api_key: str, currency: Currency) -> APIRouter:
    return orders_router(create_order_processor_place_order(create_order_processor(api_key, currency)))
```

When what an inbound edge component calls holds one request's resources, its port is an opener: a function that returns the interface. A `PhoneCall` component talks to a caller for the length of a call, over a line the router presents in the project's own shape. The `WebSocket` belongs to FastAPI's foreign interface, so it never leaves the router:

```python
# components/call_router/ports.py
from collections.abc import Callable
from typing import Protocol

class Line(Protocol): # The project's shape for a caller's connection
    async def say(self, audio: bytes) -> None: ...
    async def hear(self) -> bytes: ...

class Call(Protocol):
    async def run(self) -> None: ...

type OpenCall = Callable[[Line, CallDetails], Call] # The port: opens a call per request
```

```python
# components/call_router/implementation.py
from fastapi import APIRouter, WebSocket

def call_router(*, path: str, open_call: OpenCall) -> APIRouter:
    router = APIRouter()

    @router.websocket(path)
    async def call(websocket: WebSocket, ddiNo: str) -> None: # the humble shell
        await websocket.accept()
        await open_call(WebSocketLine(websocket), CallDetails(ddi_number=ddiNo)).run()

    return router

class WebSocketLine: # presents the foreign socket as the project's Line
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def say(self, audio: bytes) -> None:
        await self.websocket.send_bytes(audio)

    async def hear(self) -> bytes:
        return await self.websocket.receive_bytes()
```

The router's factory satisfies the opener with a factory of the phone call component:

```python
# factories/components/call_router/factory.py
def create_call_router(model: RealtimeModel) -> APIRouter:
    return call_router(path="/call", open_call=lambda line, details: create_phone_call(model, line, details))
```

## Example 5: a contract and its adapters

A `ToolRunner` component runs the tools a model calls. A tool means the same thing to every entity that uses it, so `AgentTool` is a contract. The tool runner's `tools` port takes a sequence of them:

```
src/shop/
  contracts/
    agent_tool.py              # AgentTool: a contract
  components/
    tool_runner/
      implementation.py        # ToolRunnerImpl(tools: Sequence[AgentTool])
  adapters/
    agent_tool/                # the adapters of the AgentTool contract
      order_processor/
        adapter.py             # PlaceOrderTool: places an order through the OrderProcessor component
      truncated/
        adapter.py             # TruncatedTool: a decorator, shortening what a tool returns
  factories/
    adapters/
      agent_tool/
        order_processor/       # create_place_order_tool
        truncated/             # create_truncated_tool
    components/
      tool_runner/             # create_tool_runner
```

The contract has a shape and no behaviour:

```python
# contracts/agent_tool.py
from collections.abc import Mapping
from typing import Any, Protocol

class AgentTool(Protocol): # A contract: the same meaning to every entity that uses it
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> Mapping[str, Any]: ... # the JSON Schema of execute's arguments
    async def execute(self, arguments: dict[str, Any]) -> str: ...
```

```python
# components/tool_runner/implementation.py
from collections.abc import Sequence

from shop.contracts.agent_tool import AgentTool

class ToolRunnerImpl:
    def __init__(self, tools: Sequence[AgentTool]): # A port typed by a contract, taking several implementations
        self.tools = {tool.name: tool for tool in tools}
```

Each tool is an adapter of the contract, under `adapters/agent_tool`. One joins the order processor component, so it is named for it:

```python
# adapters/agent_tool/order_processor/adapter.py
from typing import Any

from shop.components.order_processor import Order, OrderItem, OrderProcessor
from shop.contracts.agent_tool import AgentTool

class PlaceOrderTool(AgentTool): # An adapter of the contract, joining the order processor component
    name = "place_order"
    description = "Place the caller's order."
    parameters = {"type": "object", "properties": {"id": {"type": "string"}, "costs": {"type": "array"}}}

    def __init__(self, order_processor: OrderProcessor): # Takes the component's interface, never its implementation
        self.order_processor = order_processor

    async def execute(self, arguments: dict[str, Any]) -> str:
        order = Order(
            id=arguments["id"],
            items=tuple(OrderItem(name=f"item_{i}", cost=cost) for i, cost in enumerate(arguments["costs"]))
        )
        receipt = self.order_processor(order)
        return f"Charged {receipt.total} {receipt.currency}."
```

A decorator of the contract is reused by wrapping, never by importing:

```python
# adapters/agent_tool/truncated/adapter.py
from collections.abc import Mapping
from typing import Any

from shop.contracts.agent_tool import AgentTool

class TruncatedTool(AgentTool): # A decorator of the contract
    def __init__(self, inner: AgentTool, max_chars: int): # Takes the interface it satisfies
        self.inner = inner
        self.max_chars = max_chars

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def description(self) -> str:
        return self.inner.description

    @property
    def parameters(self) -> Mapping[str, Any]:
        return self.inner.parameters

    async def execute(self, arguments: dict[str, Any]) -> str:
        return (await self.inner.execute(arguments))[: self.max_chars]
```

The factories combine them:

```python
# factories/adapters/agent_tool/order_processor/factory.py
from shop.adapters.agent_tool.order_processor import PlaceOrderTool
from shop.components.order_processor import OrderProcessor
from shop.contracts.agent_tool import AgentTool
from shop.factories.adapters.agent_tool.truncated import create_truncated_tool

def create_place_order_tool(order_processor: OrderProcessor) -> AgentTool: # Returns the contract it satisfies
    return create_truncated_tool(inner=PlaceOrderTool(order_processor), max_chars=2_000)
```

```python
# factories/components/tool_runner/factory.py
from shop.components.order_processor import OrderProcessor
from shop.components.tool_runner import ToolRunner, ToolRunnerImpl
from shop.factories.adapters.agent_tool.order_processor import create_place_order_tool

def create_tool_runner(order_processor: OrderProcessor) -> ToolRunner:
    return ToolRunnerImpl(tools=[create_place_order_tool(order_processor)])
```

## Example 6: the tests

```
tests/
  unit/
    components/
      order_processor/
        test_order_processor.py    # constructs OrderProcessorImpl with FakePayments and a fixed clock
        fakes.py                   # FakePayments: the fake for this component's payments port
      checkout/
        test_checkout.py
        fakes.py                   # FakePayment
      stripe_payments/
        test_stripe_payments.py    # constructs StripePaymentsImpl with an httpx.Client on httpx.MockTransport
      orders_router/
        test_orders_router.py      # drives orders_router through FastAPI's TestClient
        fakes.py                   # FakePlaceOrder
    adapters/
      checkout/
        payment/
          order_processor/
            test_order_processor.py  # constructs OrderProcessorAdapter with FakeOrderProcessor
            fakes.py                 # FakeOrderProcessor
      agent_tool/
        truncated/
          test_truncated.py        # constructs TruncatedTool with a FakeAgentTool
          fakes.py
  integration/
    components/
      postgres_orders/
        test_postgres_orders.py    # runs PostgresOrders against a real database
  e2e/
    test_cli.py                    # where the project has end-to-end tests: runs entrypoints/cli.py
```

A test imports the entity under test from its export file and its fakes from beside itself:

```python
# tests/unit/components/order_processor/test_order_processor.py
from shop.components.order_processor import OrderProcessor, OrderProcessorImpl

from .fakes import FakePayments
```

The tests for `Checkout` do not import `FakePayments` or anything else from the order processor's tests. `Checkout` has its own ports, so its tests have their own fakes. The two `FakeOrderProcessor` fakes are duplicated for the same reason.

## Example 7: legacy code

A project has a legacy `billing.py` that already talks to Stripe. A new `OrderProcessor` component reaches it through its `payments` port, satisfied by an outbound edge component that faces the legacy code:

```
src/shop/
  billing.py                     # legacy code, left where it is
  components/
    order_processor/
    legacy_billing/
      __init__.py
      interface.py               # LegacyBilling
      implementation.py          # LegacyBillingImpl: calls billing.py
  factories/
    components/
      legacy_billing/
        factory.py               # create_legacy_billing
```

```python
# components/legacy_billing/implementation.py
from shop import billing                                  # good: the legacy code this edge component faces
from shop.contracts.currency import Currency

class LegacyBillingImpl:
    def charge(self, amount: int, currency: Currency) -> bool:
        return billing.take_payment(amount / 100, currency) == "ok"
```

Legacy code that needs an `OrderProcessor` calls its factory and uses its interface:

```python
# src/shop/views.py, legacy code
from shop.factories.components.order_processor import create_order_processor   # good: a factory
from shop.components.order_processor import OrderProcessorImpl                 # bad: the constructor
```

A task that changes how `billing.py` rounds amounts changes it in place. A task that rewrites how payments are taken may move that behaviour into a `stripe_payments` component, leaving `billing.py` calling its factory, as far as the change needs and no further.

## Checking the rules

[import-linter](https://import-linter.readthedocs.io/) can enforce the import rules:

```ini
[importlinter]
root_package = shop
include_external_packages = True

[importlinter:contract:layers]
name = Imports point inward
type = layers
layers =
    shop.entrypoints
    shop.factories
    shop.adapters
    shop.components
    shop.contracts

[importlinter:contract:independent-components]
name = Components never import each other
type = independence
modules =
    shop.components.order_processor
    shop.components.stripe_payments
    shop.components.checkout
    shop.components.orders_router

[importlinter:contract:contracts-are-pure]
name = Contracts import nothing foreign
type = forbidden
source_modules =
    shop.contracts
forbidden_modules =
    httpx
    fastapi
    pydantic

[importlinter:contract:stripe-at-the-edge]
name = Only the edge component facing Stripe's API uses httpx
type = forbidden
source_modules =
    shop.components.order_processor
    shop.components.checkout
    shop.adapters
forbidden_modules =
    httpx
```

import-linter works on files, not names, so it cannot tell an import of `OrderProcessorImpl` from an import of `OrderProcessor`. Ruff's `banned-api` setting (rule `TID251`) can: ban each constructor by its full name, `shop.components.order_processor.OrderProcessorImpl`, and switch the rule off with `per-file-ignores` for `src/shop/factories/` and `tests/`. Ban each adapter's constructor the same way.
