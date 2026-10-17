# Test-driven development in Python

Below follows an example for a TDD approach towards building an `OrderProcessor` component. Nothing exists before the first test. Files are placed as [project-structure](../project-structure.md) describes.

## First TDD Cycle

**Red**

The first behaviour to pin is that an order processor charges the total of the items in the order. Charging is a new dependency of the component, so this behaviour adds its first port, `payments`, and a fake for it is written in the same cycle:

```python
# tests/unit/components/order_processor/fakes.py
from shop.components.order_processor import Payments

class FakePayments(Payments):
    def __init__(self):
        self.charges = []

    def charge(self, amount: int) -> bool:
        self.charges.append(amount)
        return True
```

```python
# tests/unit/components/order_processor/test_order_processor.py
import pytest

from shop.components.order_processor import Order, OrderItem, OrderProcessor, OrderProcessorImpl

from .fakes import FakePayments

@pytest.fixture
def payments():
    return FakePayments()

@pytest.fixture
def order_processor(payments) -> OrderProcessor:
    return OrderProcessorImpl(payments=payments)

def order_with(costs: list[int]) -> Order:
    return Order(
        id="order_id",
        items=tuple(OrderItem(name=f"item_{i}", cost=cost) for i, cost in enumerate(costs))
    )

@pytest.mark.parametrize("costs, expected_charge", [
    ([100], 100),
    ([100, 40], 140),
])
def test_charges_the_payments_port_the_order_total(
    costs,
    expected_charge,
    payments,
    order_processor
):
    order_processor(order_with(costs))
    assert payments.charges == [expected_charge]
```

At this point the tests will fail but they will fail for the 'wrong reason'. They will fail because nothing they import exists. A true red state requires that the type checker passes but the tests are failing. So the component's package is created with just enough skeleton to get there. `Order` and `Receipt` appear in the component's interface, so they go in its data file:

```python
# components/order_processor/data.py
from dataclasses import dataclass

@dataclass(frozen=True)
class OrderItem:
    name: str
    cost: int

@dataclass(frozen=True)
class Order:
    id: str
    items: tuple[OrderItem, ...]

@dataclass(frozen=True)
class Receipt:
    total: int
```

```python
# components/order_processor/ports.py
from typing import Protocol

class Payments(Protocol):
    def charge(self, amount: int) -> bool:
        ...
```

```python
# components/order_processor/interface.py
from typing import Protocol

from .data import Order, Receipt

class OrderProcessor(Protocol):
    def __call__(self, order: Order) -> Receipt:
        ...
```

```python
# components/order_processor/implementation.py
from .data import Order, Receipt
from .ports import Payments

class OrderProcessorImpl:
    def __init__(self, payments: Payments):
        self.payments = payments

    def __call__(self, order: Order) -> Receipt:
        raise NotImplementedError
```

```python
# components/order_processor/__init__.py
from .data import Order, OrderItem, Receipt
from .implementation import OrderProcessorImpl
from .interface import OrderProcessor
from .ports import Payments

__all__ = ["Order", "OrderItem", "OrderProcessor", "OrderProcessorImpl", "Payments", "Receipt"]
```

Now the test will fail for the right reason and the red state has been completed.

**Green**

Only enough implementation to pass:

```python
# components/order_processor/implementation.py
class OrderProcessorImpl:
    def __init__(self, payments: Payments):
        self.payments = payments

    def __call__(self, order: Order) -> Receipt:
        total = 0
        for item in order.items:
            total += item.cost
        self.payments.charge(total)
        return Receipt(total=total)
```

Green state achieved.

**Refactor**

With the suite green, the loop is replaced with `sum`. No test changes, and the suite stays green:

```python
# components/order_processor/implementation.py
    def __call__(self, order: Order) -> Receipt:
        total = sum(item.cost for item in order.items)
        self.payments.charge(total)
        return Receipt(total=total)
```

## Second TDD Cycle

**Red**

The next behaviour to pin is that an order processor refuses an order the payments port declines. It needs nothing new from outside the component, so no port is added: the fake learns to decline:

```python
# tests/unit/components/order_processor/fakes.py
class FakePayments(Payments):
    def __init__(self, accepts: bool = True):
        self.accepts = accepts
        self.charges = []

    def charge(self, amount: int) -> bool:
        self.charges.append(amount)
        return self.accepts
```

```python
# tests/unit/components/order_processor/test_order_processor.py
from shop.components.order_processor import PaymentDeclined

def test_refuses_an_order_the_payments_port_declines():
    order_processor = OrderProcessorImpl(payments=FakePayments(accepts=False))
    with pytest.raises(PaymentDeclined):
        order_processor(order_with([100]))
```

The refusal is determined by the component's implementation, so the component defines the error in its errors file and exports it:

```python
# components/order_processor/errors.py
class PaymentDeclined(Exception):
    ...
```

The type checker passes and the test fails because nothing is raised: a proper red.

**Green**

```python
# components/order_processor/implementation.py
    def __call__(self, order: Order) -> Receipt:
        total = sum(item.cost for item in order.items)
        if not self.payments.charge(total):
            raise PaymentDeclined(order.id)
        return Receipt(total=total)
```

**Refactor**

Nothing is worth changing yet, so the refactor step is empty.

The cycles continue until the required behaviours are all pinned. A behaviour such as charging in a configured currency would add `currency` to the constructor as configuration and to the payments port's `charge` method, in the same cycle as its test. A behaviour such as stamping the receipt with the time it was placed needs a new dependency, so it adds a second port, `clock: Clock`, and a fake for it, in the same cycle as its test: it never adds a `now` method to the payments port.

## After the cycles

The component now exists and has only ever been constructed with fakes. The `StripePayments` edge component that will satisfy its `payments` port is driven by its own cycles, with an `httpx.Client` on the library's own test hook, `httpx.MockTransport`. The factories and the entrypoints are written last: see [project-structure](../project-structure.md) for where they go and [dependency-injection](../dependency-injection.md) for what the factories do.
