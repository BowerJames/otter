# Project Structure in Python

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their Python spelling.

## Vocabulary → Python

| Term | Python |
|---|---|
| **Package** | a directory with an `__init__.py` |
| **Export file** | the package's `__init__.py`, re-exporting names and listing them in `__all__` |
| **Data carrier** | a frozen `dataclass`, or a type alias such as a `Literal` |
| **Domain package** | `core/domain`, with one file per concept — `core/domain/currency.py` |
| **Module factory package** | `infrastructure/factories/modules/<module_name>`, with the factories in `factory.py` |
| **Adapter factory package** | `infrastructure/factories/adapters/<module_name>/<adapter_name>`, with the factories in `factory.py` |
| **Entrypoint** | a class in a file in `infrastructure/entrypoints` — `Cli` in `infrastructure/entrypoints/cli.py` |
| **Startup code** | the `if __name__ == "__main__":` block in the entrypoint's file |

Python calls every `.py` file a "module". In these skills **module** keeps its codebase-design meaning, so this file says "file" for a `.py` file.

Files behind the export file carry no `_` prefix. The export file decides what is public: a name is public if `__init__.py` re-exports it and lists it in `__all__`, and private otherwise.

## Example 1: a module and its adapters

An `OrderProcessor` module charges for an order through its `OrderProcessorPort`. A Stripe adapter and a PayPal adapter each satisfy that port.

```
src/
  core/
    domain/
      __init__.py
      currency.py              # Currency
    order_processor/
      __init__.py              # the export file
      interface.py             # OrderProcessor
      port.py                  # OrderProcessorPort
      data.py                  # Order, OrderItem, Receipt
      errors.py                # PaymentDeclined
      implementation.py        # OrderProcessorImpl; could be several files
  infrastructure/
    adapters/
      order_processor/
        stripe/
          __init__.py          # the export file
          adapter.py           # StripeAdapter
          http.py              # HTTP, RealHTTP: the adapter's own port and what satisfies it
        paypal/
          __init__.py          # the export file
          adapter.py           # PaypalAdapter
          http.py              # HTTP, RealHTTP
    factories/
      modules/
        order_processor/
          __init__.py          # the export file
          factory.py           # create_order_processor
      adapters/
        order_processor/
          stripe/
            __init__.py        # the export file
            factory.py         # create_stripe_adapter
          paypal/
            __init__.py        # the export file
            factory.py         # create_paypal_adapter
    entrypoints/
      cli.py
```

`Currency` means the same thing to every module and belongs to none, so it is in the domain package. `Order` and `Receipt` appear in the `OrderProcessor` interface, so they are in the module's data file:

```python
# core/domain/currency.py
from typing import Literal

type Currency = Literal["GBP", "USD", "EUR"]
```

```python
# core/order_processor/data.py
from dataclasses import dataclass

from core.domain.currency import Currency

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
```

The interface, the port, the errors and the implementation each have their own file:

```python
# core/order_processor/interface.py
from typing import Protocol

from .data import Order, Receipt

class OrderProcessor(Protocol): # Interface for the module
    def __call__(self, order: Order) -> Receipt: ...
```

```python
# core/order_processor/port.py
from typing import Protocol

from core.domain.currency import Currency

class OrderProcessorPort(Protocol): # The module's port
    def charge(self, amount: int, currency: Currency) -> bool: ...
```

```python
# core/order_processor/errors.py
class PaymentDeclined(Exception): # Determined by the module's implementation
    ...
```

```python
# core/order_processor/implementation.py
from core.domain.currency import Currency

from .data import Order, Receipt
from .errors import PaymentDeclined
from .port import OrderProcessorPort

class OrderProcessorImpl: # Implementation of the module
    def __init__(
        self,
        port: OrderProcessorPort,
        currency: Currency
    ): # Constructor for the module
        self.port = port
        self.currency = currency

    def __call__(self, order: Order) -> Receipt:
        ...
```

```python
# core/order_processor/__init__.py
from .data import Order, OrderItem, Receipt
from .errors import PaymentDeclined
from .implementation import OrderProcessorImpl
from .interface import OrderProcessor
from .port import OrderProcessorPort

__all__ = [
    "Order",
    "OrderItem",
    "OrderProcessor",
    "OrderProcessorImpl",
    "OrderProcessorPort",
    "PaymentDeclined",
    "Receipt",
]
```

An adapter imports the port from the module's export file:

```python
# infrastructure/adapters/order_processor/stripe/adapter.py
from core.domain.currency import Currency
from core.order_processor import OrderProcessorPort                # good: the export file
from core.order_processor.port import OrderProcessorPort           # bad: reaches behind the export file
from infrastructure.adapters.order_processor.paypal import ...     # bad: an adapter importing another adapter

from .http import HTTP                                             # good: the adapter's own port, defined in its own package

class StripeAdapter(OrderProcessorPort): # Adapter for the module's port
    def __init__(self, api_key: str, http: HTTP): ... # Constructor for the stripe adapter

    def charge(self, amount: int, currency: Currency) -> bool: ...
```

Nothing in `core` imports from `infrastructure`:

```python
# core/order_processor/implementation.py
from infrastructure.adapters.order_processor.stripe import StripeAdapter   # bad: the core importing an adapter
```

## Example 2: the factory packages and an entrypoint

The adapter's export file exports what its adapter factory needs to build it: its constructor, its own port, and what satisfies that port in production:

```python
# infrastructure/adapters/order_processor/stripe/__init__.py
from .adapter import StripeAdapter
from .http import HTTP, RealHTTP

__all__ = ["HTTP", "RealHTTP", "StripeAdapter"]
```

The adapter factory builds the adapter's parts and calls its constructor. It lives under `infrastructure/factories/adapters`, at the adapter's path:

```python
# infrastructure/factories/adapters/order_processor/stripe/factory.py
from core.order_processor import OrderProcessorPort
from infrastructure.adapters.order_processor.stripe import RealHTTP, StripeAdapter

def create_stripe_adapter(api_key: str) -> OrderProcessorPort: # An adapter factory: returns the port the adapter satisfies
    return StripeAdapter(api_key, RealHTTP())
```

```python
# infrastructure/factories/adapters/order_processor/stripe/__init__.py
from .factory import create_stripe_adapter

__all__ = ["create_stripe_adapter"]
```

The module factory chooses an adapter by calling its adapter factory, and never imports from an adapter's package:

```python
# infrastructure/factories/modules/order_processor/factory.py
from typing import Literal

from core.domain.currency import Currency
from core.order_processor import OrderProcessor, OrderProcessorImpl
from infrastructure.factories.adapters.order_processor.paypal import create_paypal_adapter
from infrastructure.factories.adapters.order_processor.stripe import create_stripe_adapter
from infrastructure.adapters.order_processor.stripe import StripeAdapter   # bad: a module factory reaching into an adapter's package

def create_order_processor(
        provider: Literal["stripe", "paypal"],
        api_key: str,
        currency: Currency
    ) -> OrderProcessor: # A module factory for the order processor module
    if provider == "stripe":
        port = create_stripe_adapter(api_key)
    elif provider == "paypal":
        port = create_paypal_adapter(api_key)
    return OrderProcessorImpl(port, currency)
```

```python
# infrastructure/factories/modules/order_processor/__init__.py
from .factory import create_order_processor

__all__ = ["create_order_processor"]
```

The entrypoint's constructor takes the entity it drives, and the entrypoint translates between the outside world and data carriers. The startup code beside it reads the environment, calls the factory and passes the entity to the entrypoint's constructor:

```python
# infrastructure/entrypoints/cli.py
import os
import sys

from core.order_processor import Order, OrderItem, OrderProcessor
from infrastructure.factories.modules.order_processor import create_order_processor

class Cli: # The entrypoint: calls no module's constructor and no factory, imports no adapter
    def __init__(self, order_processor: OrderProcessor): # Its constructor takes the interface it drives
        self.order_processor = order_processor

    def __call__(self, argv: list[str]) -> None:
        order = Order(
            id=argv[0],
            items=tuple(OrderItem(name=f"item_{i}", cost=int(cost)) for i, cost in enumerate(argv[1:]))
        ) # translate the outside world into a data carrier
        receipt = self.order_processor(order)
        print(f"total={receipt.total} {receipt.currency}")

if __name__ == "__main__": # The startup code
    cli = Cli(
        create_order_processor(
            provider="stripe",
            api_key=os.environ["STRIPE_API_KEY"],
            currency="GBP"
        )
    )
    cli(sys.argv[1:])
```

## Example 3: a module that needs another module

A `Checkout` module is built on top of order processing. It does not import `core/order_processor`. It declares its own data carriers and a port with the shape it needs:

```python
# core/checkout/data.py
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
# core/checkout/port.py
from typing import Protocol

from .data import Cart

class CheckoutPort(Protocol): # The checkout module's port
    def pay(self, cart: Cart) -> int: ...
```

An adapter under `infrastructure/adapters/checkout` satisfies the port by calling an `OrderProcessor` through its interface, translating between the two modules' data carriers:

```python
# infrastructure/adapters/checkout/order_processor/adapter.py
from core.checkout import Cart, CheckoutPort
from core.order_processor import Order, OrderItem, OrderProcessor

class OrderProcessorAdapter(CheckoutPort): # Adapter connecting checkout to the order processor module
    def __init__(self, order_processor: OrderProcessor): # Constructor takes the interface, never the implementation
        self.order_processor = order_processor

    def pay(self, cart: Cart) -> int:
        order = Order(
            id=cart.id,
            items=tuple(OrderItem(name=line.product, cost=line.price) for line in cart.lines)
        ) # checkout's data, translated into the order processor's
        return self.order_processor(order).total
```

The adapter's factory gets an `OrderProcessor` from the order processor's module factory package and passes it to the adapter's constructor:

```python
# infrastructure/factories/adapters/checkout/order_processor/factory.py
from core.checkout import CheckoutPort
from infrastructure.adapters.checkout.order_processor import OrderProcessorAdapter
from infrastructure.factories.modules.order_processor import create_order_processor

def create_order_processor_adapter(api_key: str) -> CheckoutPort: # An adapter factory for the connecting adapter
    return OrderProcessorAdapter(create_order_processor("stripe", api_key, "GBP"))
```

The checkout module factory gets its adapter from that factory:

```python
# infrastructure/factories/modules/checkout/factory.py
from core.checkout import Checkout, CheckoutImpl
from infrastructure.factories.adapters.checkout.order_processor import create_order_processor_adapter

def create_checkout(api_key: str) -> Checkout: # A module factory for the checkout module
    return CheckoutImpl(create_order_processor_adapter(api_key))
```

## Example 4: the tests

```
tests/
  unit/
    core/
      order_processor/
        test_order_processor.py    # constructs OrderProcessorImpl with FakeOrderProcessorAdapter
        adapters.py                # FakeOrderProcessorAdapter: the test adapter for this module's port
      checkout/
        test_checkout.py
        adapters.py                # FakeCheckoutAdapter
    infrastructure/
      adapters/
        order_processor/
          stripe/
            test_stripe.py         # constructs StripeAdapter with FakeHTTP
            adapters.py            # FakeHTTP
        checkout/
          order_processor/
            test_order_processor.py  # constructs OrderProcessorAdapter with FakeOrderProcessor
            adapters.py              # FakeOrderProcessor
      entrypoints/
        test_cli.py                # constructs Cli with FakeOrderProcessor
        adapters.py                # FakeOrderProcessor
  integration/
    infrastructure/
      adapters/
        order_processor/
          postgres/
            test_postgres.py       # runs PostgresAdapter against a real database
  e2e/
    test_cli.py                    # where the project has end-to-end tests: runs the startup code
```

A test imports the entity under test from its export file and its test adapters from beside itself:

```python
# tests/unit/core/order_processor/test_order_processor.py
from core.order_processor import OrderProcessor, OrderProcessorImpl

from .adapters import FakeOrderProcessorAdapter
```

The tests for `Checkout` do not import `FakeOrderProcessorAdapter` or anything else from the order processor's tests. `Checkout` has its own port, so its tests have their own test adapter. The two `FakeOrderProcessor` test adapters are duplicated for the same reason.

## Example 5: legacy code

A project has a legacy `billing.py` that already talks to Stripe. A new `OrderProcessor` module reaches it through its port, with an adapter named for it:

```
src/
  billing.py                     # legacy code, left where it is
  core/
    order_processor/
  infrastructure/
    adapters/
      order_processor/
        legacy_billing/
          __init__.py
          adapter.py             # LegacyBillingAdapter: satisfies OrderProcessorPort by calling billing.py
    factories/
      adapters/
        order_processor/
          legacy_billing/
            __init__.py
            factory.py           # create_legacy_billing_adapter
```

```python
# infrastructure/adapters/order_processor/legacy_billing/adapter.py
import billing

from core.domain.currency import Currency
from core.order_processor import OrderProcessorPort

class LegacyBillingAdapter(OrderProcessorPort):
    def charge(self, amount: int, currency: Currency) -> bool:
        return billing.take_payment(amount / 100, currency) == "ok"
```

Legacy code that needs an `OrderProcessor` calls the factory and drives the interface:

```python
# src/views.py, legacy code
from infrastructure.factories.modules.order_processor import create_order_processor   # good: a module factory
from core.order_processor import OrderProcessorImpl                                  # bad: the constructor
```

## Checking the rules

[import-linter](https://import-linter.readthedocs.io/) can enforce the import rules: a `layers` contract places `infrastructure` above `core`, a `forbidden` contract stops `core.domain` importing from any module's package, and an `independence` contract stops the packages of modules importing each other. A `forbidden` contract with `include_external_packages` can also stop `core` importing any third-party library.

import-linter works on files, not names, so it cannot tell an import of `OrderProcessorImpl` from an import of `OrderProcessor`. Ruff's `banned-api` setting (rule `TID251`) can: ban each constructor by its full name, `core.order_processor.OrderProcessorImpl`, and switch the rule off with `per-file-ignores` for `src/infrastructure/factories/modules/` and `tests/`. Ban each adapter's constructor the same way, with the rule switched off for `src/infrastructure/factories/adapters/` and `tests/`.
