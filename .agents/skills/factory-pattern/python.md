# Factory Pattern in Python

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [codebase-design's python.md](../codebase-design/python.md).

## Example

Bad example for a `PaymentGateway` module:

```python
class PaymentGateway(Protocol):

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
        type: Literal["stripe", "paypal"],
        env_variable_loader: EnvVariableLoader,
        http: HTTP
    ) -> StripeGateway | PaypalGateway: # This is not a factory for the PaymentGateway module as it declares the return type as an implementation of the module, not the module interface.
    if type == "stripe":
        api_key = env_variable_loader("STRIPE_API_KEY")
        return StripeGateway(api_key, http)
    elif type == "paypal":
        api_key = env_variable_loader("PAYPAL_API_KEY")
        return PaypalGateway(api_key, http)
```

Good example for a `PaymentGateway` module:

```python
class PaymentGateway(Protocol):

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
        type: Literal["stripe", "paypal"],
        env_variable_loader: EnvVariableLoader,
        http: HTTP
    ) -> PaymentGateway: # This is now a factory for the PaymentGateway module since it declares the return type as the interface for the module.
    if type == "stripe":
        api_key = env_variable_loader("STRIPE_API_KEY")
        return StripeGateway(api_key, http)
    elif type == "paypal":
        api_key = env_variable_loader("PAYPAL_API_KEY")
        return PaypalGateway(api_key, http)
```