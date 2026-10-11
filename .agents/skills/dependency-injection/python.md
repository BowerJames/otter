# Dependency Injection in Python

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [codebase-design's python.md](../codebase-design/python.md).

## Rule 1: code against interfaces

Bad example for an `OrderProcessor` module:

```python
class StripeGateway:

    def __init__(
        self,
        api_key,
        http
    ): ...

    def charge(self, amount: float) -> bool: ...

type OrderProcessor = Callable[[Order], Receipt]

def create_order_processor(
    gateway: StripeGateway # The factory for the OrderProcessor is using the StripeGateway class which includes its implementation.
) -> OrderProcessor:
    ...
```

Good example for an `OrderProcessor` module:

```python
class PaymentGateway(Protocol):

    def charge(self, amount: float) -> bool: ...

type OrderProcessor = Callable[[Order], Receipt]

def create_order_processor(
    gateway: PaymentGateway # The factory for the OrderProcessor is using the PaymentGateway interface which can be substituted for any PaymentGateway.
) -> OrderProcessor:
    ...

```

## Rule 2: declare seams in factories

Avoid for an `OrderProcessor` module:

```python
class PaymentGateway(Protocol):

    def charge(self, amount: float) -> bool: ...

type OrderProcessor = Callable[[Order, PaymentGateway], Receipt]

def process_order(
    order: Order,
    gateway: PaymentGateway # The seam that changes the capability of the order processor exists in the interface
) -> Receipt:
    total = 0
    for item in order.items:
        total += item.cost
    payment_successful = gateway.charge(total)
    if not payment_successful:
        raise ...
    return Receipt(
        total=total
    )
```

Prefer for an `OrderProcessor` module:

```python
class PaymentGateway(Protocol):

    def charge(self, amount: float) -> bool: ...

type OrderProcessor = Callable[[Order], Receipt]

def create_order_processor(
    gateway: PaymentGateway # Seam is passed in the factory for the OrderProcessor module
) -> OrderProcessor:
    def process_order(order: Order) -> Receipt:
        total = 0
        for item in order.items:
            total += item.cost
        payment_successful = gateway.charge(total)
        if not payment_successful:
            raise ...
        return Receipt(
            total=total
        )
    return process_order
```