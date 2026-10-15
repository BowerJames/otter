# Test-driven development in Python

Below follows an example for a TDD approach towards building an `OrderProcessor` module. Nothing exists before the first test. Files are placed as [project-structure](../project-structure/SKILL.md) describes.

## First TDD Cycle

**Red**

The first behaviour to pin is that an order processor charges the total of the items in the order. Charging reaches outside the module, so this behaviour needs the module's port, and a test adapter for it is written in the same cycle:

```python
# tests/unit/core/order_processor/adapters.py
from core.order_processor import OrderProcessorPort

class FakeOrderProcessorAdapter(OrderProcessorPort):
    def __init__(self):
        self.charges = []

    def charge(self, amount: int) -> bool:
        self.charges.append(amount)
        return True
```

```python
# tests/unit/core/order_processor/test_order_processor.py
import pytest

from core.order_processor import Order, OrderItem, OrderProcessor, OrderProcessorImpl

from .adapters import FakeOrderProcessorAdapter

@pytest.fixture
def port():
    return FakeOrderProcessorAdapter()

@pytest.fixture
def order_processor(port) -> OrderProcessor:
    return OrderProcessorImpl(port=port)

def order_with(costs: list[int]) -> Order:
    return Order(
        id="order_id",
        items=tuple(OrderItem(name=f"item_{i}", cost=cost) for i, cost in enumerate(costs))
    )

@pytest.mark.parametrize("costs, expected_charge", [
    ([100], 100),
    ([100, 40], 140),
])
def test_charges_the_port_the_order_total(
    costs,
    expected_charge,
    port,
    order_processor
):
    order_processor(order_with(costs))
    assert port.charges == [expected_charge]
```

At this point the tests will fail but they will fail for the 'wrong reason'. They will fail because nothing they import exists. A true red state requires that the type checker passes but the tests are failing. So the module's package is created with just enough skeleton to get there. `Order` and `Receipt` appear in the module's interface, so they go in its data file:

```python
# core/order_processor/data.py
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
# core/order_processor/port.py
from typing import Protocol

class OrderProcessorPort(Protocol):
    def charge(self, amount: int) -> bool:
        ...
```

```python
# core/order_processor/interface.py
from typing import Protocol

from .data import Order, Receipt

class OrderProcessor(Protocol):
    def __call__(self, order: Order) -> Receipt:
        ...
```

```python
# core/order_processor/implementation.py
from .data import Order, Receipt
from .port import OrderProcessorPort

class OrderProcessorImpl:
    def __init__(self, port: OrderProcessorPort):
        self.port = port

    def __call__(self, order: Order) -> Receipt:
        raise NotImplementedError
```

```python
# core/order_processor/__init__.py
from .data import Order, OrderItem, Receipt
from .implementation import OrderProcessorImpl
from .interface import OrderProcessor
from .port import OrderProcessorPort

__all__ = ["Order", "OrderItem", "OrderProcessor", "OrderProcessorImpl", "OrderProcessorPort", "Receipt"]
```

Now the test will fail for the right reason and the red state has been completed.

**Green**

Only enough implementation to pass:

```python
# core/order_processor/implementation.py
class OrderProcessorImpl:
    def __init__(self, port: OrderProcessorPort):
        self.port = port

    def __call__(self, order: Order) -> Receipt:
        total = 0
        for item in order.items:
            total += item.cost
        self.port.charge(total)
        return Receipt(total=total)
```

Green state achieved.

**Refactor**

With the suite green, the loop is replaced with `sum`. No test changes, and the suite stays green:

```python
# core/order_processor/implementation.py
    def __call__(self, order: Order) -> Receipt:
        total = sum(item.cost for item in order.items)
        self.port.charge(total)
        return Receipt(total=total)
```

## Second TDD Cycle

**Red**

The next behaviour to pin is that an order processor refuses an order the port declines. The test adapter learns to decline:

```python
# tests/unit/core/order_processor/adapters.py
class FakeOrderProcessorAdapter(OrderProcessorPort):
    def __init__(self, accepts: bool = True):
        self.accepts = accepts
        self.charges = []

    def charge(self, amount: int) -> bool:
        self.charges.append(amount)
        return self.accepts
```

```python
# tests/unit/core/order_processor/test_order_processor.py
from core.order_processor import PaymentDeclined

def test_refuses_an_order_the_port_declines():
    order_processor = OrderProcessorImpl(port=FakeOrderProcessorAdapter(accepts=False))
    with pytest.raises(PaymentDeclined):
        order_processor(order_with([100]))
```

The refusal is determined by the module's implementation, so the module defines the error in its errors file and exports it:

```python
# core/order_processor/errors.py
class PaymentDeclined(Exception):
    ...
```

The type checker passes and the test fails because nothing is raised: a proper red.

**Green**

```python
# core/order_processor/implementation.py
    def __call__(self, order: Order) -> Receipt:
        total = sum(item.cost for item in order.items)
        if not self.port.charge(total):
            raise PaymentDeclined(order.id)
        return Receipt(total=total)
```

**Refactor**

Nothing is worth changing yet, so the refactor step is empty.

The cycles continue until the required behaviours are all pinned. A behaviour such as charging in a configured currency would add `currency` to the constructor as configuration and to the port's `charge` method, in the same cycle as its test.

## After the cycles

The module now exists in the core and has only ever been constructed with a test adapter. The Stripe adapter for `OrderProcessorPort` is driven by its own cycles, with a test adapter for its HTTP port. The adapter factories, the module factory and the startup code are written last: see [project-structure](../project-structure/SKILL.md) for where they go and [dependency-injection](../dependency-injection/SKILL.md) for what the factories do.
