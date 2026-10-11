# Codebase Design in Python

The vocabulary in [SKILL.md](SKILL.md) is language-agnostic. This file is its Python spelling.

## Vocabulary → Python

| Term | Python |
|---|---|
| **Interface** | for classes, a `typing.Protocol`; for functions, a type — `Callable[[], datetime]` |
| **Adapter** | any class or function satisfying the interface's shape |
| **Seam** | a typed parameter capability varies through: an object interface, a function interface, or a plain value |

## Example 1

Below illustrates an example of a `PaymentGateway` module in Python.

```python
from typing import Protocol, Literal

type EnvVariableLoader = Callable[[str], str]
type HTTP = Callable[[Request], Response]

class PaymentGateway(Protocol):          # the interface for the PaymentGateway Module
    def charge(self, amount: float) -> bool: ...

class StripeGateway:
    def __init__(
        self,
        api_key: str,
        http: HTTP
    ): ...

    def charge(self, amount: float) -> bool: ...

class PaypalGateway:
    def __init__(
        self,
        api_key: str,
        http: HTTP
    ): ...

    def charge(self, amount: float) -> bool: ...

def create_payment_gateway(
        type: Literal["stripe", "paypal"], # seam for the PaymentGateway Module
        env_variable_loader: EnvVariableLoader, # seam for the PaymentGateway Module to access the environment variable resource for testing
        http: HTTP
    ) -> PaymentGateway: # A factory for the PaymentGateway module
    if type == "stripe":
        api_key = env_variable_loader("STRIPE_API_KEY")
        return StripeGateway(api_key, http)
    elif type == "paypal":
        api_key = env_variable_loader("PAYPAL_API_KEY")
        return PaypalGateway(api_key, http)
```

Matching is structural: `StripeGateway` and `PaypalGateway` both satisfy the `PaymentGateway` interface.

Explicit inheritance (`class StripeGateway(PaymentGateway)`) is allowed and documents intent — it lets the type checker flag drift — but it is a declaration, never a requirement.

This module is a well designed deep module:

**Leverage for the caller** - The module allows the caller to make payments through stripe and paypal through a simple interface with a single method with a single parameter.

**Flexibility for developers** - It is simple to extend the module capabilities by simply adding another class satisfying the `PaymentGateway` interface and adding a single extra conditional branch in the implementation of the factory.

**Testability for everyone** - The module can be tested easily through its factory and interface by providing test adapters for the env loader and http dependencies to observe behaviours through.

## Example 2

Below are 2 valid formulations of an `OrderProcessor` module built on top of example 1.

```python
from typing import Callable

type OrderProcessor = Callable[[Order, PaymentGateway], Receipt] # Interface for the OrderProcessor module

def process_order(
    order: Order,
    gateway: PaymentGateway # seam through which capabilities of the OrderProcessor can vary
) -> Receipt:
    # Implementation of the OrderProcessor module
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

```python
from typing import Callable

type OrderProcessor = Callable[[Order], Receipt] # Interface for the OrderProcessor module

def create_order_processor(
    gateway: PaymentGateway # A seam for the OrderProcessor module
) -> OrderProcessor: # Factory of the OrderProcessor module
    def process_order(
        order: Order
    ) -> Receipt:
        # Implementation of the OrderProcessor module
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

Both are modules with a seam; they differ in where the seam sits. The first places it in the interface, so every caller must supply a gateway. The second places it in the factory, leaving the interface with only data. Prefer the second wherever the adapter is known when the entity is created (see dependency-injection, rule 2).

The second example exhibits:

**Leverage for Consumers** - Has the capability to total orders and process payments through Stripe and Paypal (thanks to the existing adapters)

**Locality for Maintainers** - Tests can be written with a fake payment gateway allowing them to localise bugs in the order totaling vs payment gateways. Any change to the order processing can be propagated to all payment gateway types through one place.

**Testability for Everyone** - A fake payment gateway allows tests to pin a single behaviour "Charges payment gateway with total equal to the sum of the cost of all items in the order" and the module gains the capability for all gateway types. One behaviour giving a range of capabilities.