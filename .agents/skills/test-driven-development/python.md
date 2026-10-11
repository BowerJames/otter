# Test-driven development in Python

Below follows an example for a TDD approach towards building an `OrderProcessor` module. We can assume elsewhere in the codebase the following `PaymentGateway` module has already been designed and has the following interface:

```python
class PaymentGateway(Protocol):

    def charge(self, amount: float) -> bool: ...
```

## First TDD Cycle

**Red**

The first thing we need is a factory for producing order processors:

```python
import pytest

from order_processor import create_order_processor, OrderProcessor

@pytest.fixture
def order_processor():
    return create_order_processor()

def test_can_create_order_processor(order_processor):
    pass
```

At this point the tests will fail but they will fail for the 'wrong reason'. They will fail because `create_order_processor` and `OrderProcessor` will not import. A true red state requires that the type checker passes but the tests are failing. So the following is added to the source code.

```python
from typing import Protocol

class OrderProcessor(Protocol):
    ...

def create_order_processor() -> OrderProcessor:
    raise NotImplementedError
```

Now the test will fail for the right reason and the red state has been completed.

**Green**

```python
from typing import Protocol

class OrderProcessor(Protocol):
    ...

def create_order_processor() -> OrderProcessor:
    return object()
```

Green state achieved.

## Second TDD Cycle

**Red**

The next behaviour to pin would be that an order processor charges the payment gateway with the total of the items in the order. To do this we need to introduce a seam for the `PaymentGateway` interface and the `Order` data carrier. Start with creating a fake payment gateway:

```python
class FakePaymentGateway():
    def __init__(self):
        self.charges = []

    def charge(self, amount: float) -> bool:
        self.charges.append(amount)
        return True
```

Then update the tests:

```python
import pytest

from order_processor import create_order_processor, OrderProcessor
from .fakes import FakePaymentGateway

@pytest.fixture
def payment_gateway():
    return FakePaymentGateway()

@pytest.fixture
def order_processor(payment_gateway):
    return create_order_processor(
        payment_gateway=payment_gateway
    )

def order_with(prices: list[float]):
    order_items = [
        OrderItem(
            name=f"item_{i}",
            cost=price
        ) for i, price in enumerate(prices)
    ]
    return Order(
        id="order_id",
        items=order_items
    )

def test_can_create_order_processor(
    order_processor
):
    pass

@pytest.mark.parametrize("prices, expected_charge", [
    ([100], 100),
    ([100, 40], 140),
])
def test_charges_total_of_all_order_items(
    prices,
    expected_charge,
    payment_gateway,
    order_processor
):
    order = order_with(prices)
    order_processor(order)
    assert payment_gateway.charges == [expected_charge]
```

Now the type checker needs to be made to pass:

```python
from typing import Protocol

from payment_gateway import PaymentGateway

class OrderProcessor(Protocol):
    def __call__(self, order: Order) -> Receipt:
        ...

def create_order_processor(payment_gateway: PaymentGateway) -> OrderProcessor:
    def order_processor(order: Order) -> Receipt:
        raise NotImplementedError
    return order_processor
```

**Green**

```python
from typing import Protocol

from payment_gateway import PaymentGateway

class OrderProcessor(Protocol):
    def __call__(self, order: Order) -> Receipt:
        ...

def create_order_processor(payment_gateway: PaymentGateway) -> OrderProcessor:
    
    def order_processor(order: Order) -> Receipt:
        total = sum(
            [
                item.cost for item in order.items
            ]
        )
        payment_gateway.charge(total)
        return Receipt(
            total=total
        )

    return order_processor
```

This completes the second cycle. And the cycles would continue until the required behaviours are all pinned.
