# Dependency Injection in Python

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [codebase-design's python.md](../codebase-design/python.md).

# The constructor

## Rule 1: a constructor takes the module's port and its configuration

Bad examples for an `OrderProcessor` module:

```python
from infrastructure.adapters.order_processor.stripe import StripeAdapter

class OrderProcessorImpl:
    def __init__(
        self,
        port: StripeAdapter # The constructor names an adapter's type, which includes its implementation.
    ): ...

    def __call__(self, order: Order) -> Receipt: ...
```

```python
from core.payment_gateway import PaymentGateway

class OrderProcessorImpl:
    def __init__(
        self,
        port: PaymentGateway # The constructor names another module's interface, so a change to that module reaches this one.
    ): ...

    def __call__(self, order: Order) -> Receipt: ...
```

```python
class PaymentPort(Protocol):
    def charge(self, amount: int, currency: Currency) -> bool: ...

type ClockPort = Callable[[], datetime]

class OrderProcessorImpl:
    def __init__(
        self,
        payment: PaymentPort,
        clock: ClockPort # A second port: the module's needs are split across two interfaces.
    ): ...
```

```python
class OrderProcessorPort(Protocol): # The port is copied from what Stripe offers, not from what the module calls.
    def charge(self, amount: int, currency: Currency) -> bool: ...
    def refund(self, amount: int, currency: Currency) -> bool: ...
    def list_charges(self) -> list[Charge]: ...
```

Good example for an `OrderProcessor` module:

```python
class OrderProcessorPort(Protocol): # The module's one port, declared by the module, holding only what it calls.
    def charge(self, amount: int, currency: Currency) -> bool: ...
    def now(self) -> datetime: ...

class OrderProcessorImpl:
    def __init__(
        self,
        port: OrderProcessorPort, # The port: any adapter satisfying it can be passed.
        currency: Currency # Configuration: a value, passed as its concrete type.
    ): ...

    def __call__(self, order: Order) -> Receipt: ...
```

A `Refunds` module that also needs Stripe declares its own port. Each module has its own adapter, and the two adapters are thin wrappers around the same resource:

```python
class RefundsPort(Protocol): # The port of the refunds module
    def refund(self, amount: int, currency: Currency) -> bool: ...
```

```python
class StripeAdapter(OrderProcessorPort): # infrastructure/adapters/order_processor/stripe
    def __init__(self, api_key: str, http: HTTP): ...

    def charge(self, amount: int, currency: Currency) -> bool: ...
    def now(self) -> datetime: ... # a whole adapter: it satisfies every method of the port

class StripeAdapter(RefundsPort): # infrastructure/adapters/refunds/stripe
    def __init__(self, api_key: str, http: HTTP): ...

    def refund(self, amount: int, currency: Currency) -> bool: ...
```

An adapter's constructor can take anything, but like every constructor it must take everything required to measure the adapter's behaviours:

```python
class StripeAdapter(OrderProcessorPort):
    def __init__(self, api_key: str):
        self.http = RealHTTP() # bad: created inside, so a test cannot measure what is sent
```

```python
class StripeAdapter(OrderProcessorPort):
    def __init__(
        self,
        api_key: str,
        http: HTTP # good: passed in, so a test can pass its own and measure what is sent
    ): ...
```

## Rule 2: the port and configuration go in the constructor, not the interface

Avoid for an `OrderProcessor` module:

```python
type OrderProcessor = Callable[[Order, OrderProcessorPort], Receipt]

class OrderProcessorImpl:
    def __call__(
        self,
        order: Order,
        port: OrderProcessorPort # The port that changes the capability of the order processor is in the interface, so every caller must supply it.
    ) -> Receipt:
        ...
```

Prefer for an `OrderProcessor` module:

```python
type OrderProcessor = Callable[[Order], Receipt]

class OrderProcessorImpl:
    def __init__(
        self,
        port: OrderProcessorPort, # The port is passed to the constructor, so the interface takes only the order.
        currency: Currency
    ):
        self.port = port
        self.currency = currency

    def __call__(self, order: Order) -> Receipt:
        total = sum(item.cost for item in order.items)
        if not self.port.charge(total, self.currency):
            raise PaymentDeclined(order.id)
        return Receipt(total=total, currency=self.currency)
```

## Rule 3: a constructor accepts what it needs, and reaches no resource

Avoid a constructor or implementation that creates or fetches what it needs:

```python
class OrderProcessorImpl:
    def __init__(self):
        api_key = os.environ["STRIPE_API_KEY"]   # fetches a resource
        self.port = StripeAdapter(api_key, RealHTTP())  # creates its own adapter
        self.currency = os.environ["CURRENCY"]   # fetches its own configuration

    def __call__(self, order: Order) -> Receipt:
        placed_at = datetime.now()               # fetches a resource
        ...
```

Prefer a constructor that accepts all of it, with the clock reached through the port:

```python
class OrderProcessorImpl:
    def __init__(
        self,
        port: OrderProcessorPort, # the port, which also tells the time
        currency: Currency # configuration
    ):
        self.port = port
        self.currency = currency

    def __call__(self, order: Order) -> Receipt:
        placed_at = self.port.now()
        ...
```

An adapter's constructor stores what it is given. It reaches its resource only when called:

```python
class PostgresAdapter(OrderProcessorPort):
    def __init__(self, dsn: str):
        self.connection = psycopg.connect(dsn) # bad: constructing the adapter opens a connection
```

```python
class PostgresAdapter(OrderProcessorPort):
    def __init__(self, connection: Connection): # good: the connection was opened by whatever called the factory
        self.connection = connection
```

# The factory

The examples build on the `OrderProcessor` module above and two adapters for its port, each with its adapter factory:

```python
# infrastructure/factories/adapters/order_processor/stripe/factory.py
def create_stripe_adapter(api_key: str) -> OrderProcessorPort: # An adapter factory: it returns the port
    return StripeAdapter(api_key, RealHTTP()) # It builds the parts defined in the adapter's package

# infrastructure/factories/adapters/order_processor/paypal/factory.py
def create_paypal_adapter(api_key: str) -> OrderProcessorPort:
    return PaypalAdapter(api_key, RealHTTP())
```

## Rule 4: a factory returns the interface

Bad examples:

```python
def create_order_processor(
        provider: Literal["stripe", "paypal"],
        api_key: str,
        currency: Currency
    ) -> OrderProcessorImpl: # This is not a factory for the OrderProcessor module as it declares the return type as the implementation of the module, not the module interface.
    ...

def create_stripe_adapter(api_key: str) -> StripeAdapter: # The adapter factory returns the adapter's implementation, not the port it satisfies.
    ...
```

Good example:

```python
def create_order_processor(
        provider: Literal["stripe", "paypal"],
        api_key: str,
        currency: Currency
    ) -> OrderProcessor: # A module factory declares the module's interface as its return type.
    if provider == "stripe":
        port = create_stripe_adapter(api_key)
    elif provider == "paypal":
        port = create_paypal_adapter(api_key)
    return OrderProcessorImpl(port, currency)
```

## Rule 5: a factory only wires

Bad example:

```python
def create_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    order_processor = OrderProcessorImpl(create_stripe_adapter(api_key), currency)

    def with_retry(order: Order) -> Receipt: # Retrying is a behaviour, and no test adapter can reach it here.
        for _ in range(3):
            try:
                return order_processor(order)
            except ConnectionError:
                continue
        raise ...

    return with_retry
```

Retrying belongs behind a constructor: in `OrderProcessorImpl`, or in an adapter that wraps another adapter of the same port. The factories then only choose and construct:

```python
# infrastructure/factories/adapters/order_processor/retrying/factory.py
def create_retrying_adapter(inner: OrderProcessorPort, attempts: int) -> OrderProcessorPort:
    return RetryingAdapter(inner, attempts)
```

```python
def create_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    port = create_retrying_adapter(create_stripe_adapter(api_key), attempts=3)
    return OrderProcessorImpl(port, currency)
```

## Rule 6: a factory reaches no resource

Bad example:

```python
def create_stripe_adapter() -> OrderProcessorPort:
    return StripeAdapter(
        api_key=os.environ["STRIPE_API_KEY"], # The factory reads the environment.
        http=RealHTTP()
    )
```

Good example, with the values passed in by whatever calls the factory:

```python
def create_stripe_adapter(api_key: str) -> OrderProcessorPort:
    return StripeAdapter(
        api_key=api_key,
        http=RealHTTP() # Constructing reaches no resource: RealHTTP only reaches the network when called.
    )

def create_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    return OrderProcessorImpl(create_stripe_adapter(api_key), currency)
```

```python
# the program's startup code, an entrypoint or a settings loader: whichever the design chooses
order_processor = create_order_processor(
    api_key=os.environ["STRIPE_API_KEY"],
    currency="GBP"
)
```

A connection is opened outside the factories too, and passed in:

```python
def create_postgres_adapter(connection: Connection) -> OrderProcessorPort:
    return PostgresAdapter(connection)

def create_order_processor(connection: Connection, currency: Currency) -> OrderProcessor:
    return OrderProcessorImpl(create_postgres_adapter(connection), currency)
```

## Rule 7: one constructor, many factories

Each factory is one way of supplying the single constructor:

```python
def create_stripe_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    return OrderProcessorImpl(create_stripe_adapter(api_key), currency)

def create_in_memory_order_processor(currency: Currency) -> OrderProcessor:
    return OrderProcessorImpl(create_in_memory_adapter(), currency)
```

Bad example, a second way of constructing added to the implementation:

```python
class OrderProcessorImpl:
    def __init__(self, port: OrderProcessorPort, currency: Currency): ...

    @classmethod
    def with_stripe(cls, api_key: str) -> "OrderProcessorImpl": # A second constructor: the implementation now knows about an adapter.
        return cls(StripeAdapter(api_key, RealHTTP()), "GBP")
```

## Rule 8: a factory calls one entity's constructor, and gets everything else from factories

Bad examples:

```python
def create_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    port = StripeAdapter(api_key, RealHTTP()) # A module factory calls an adapter's constructor, so it must know what the adapter is made of.
    return OrderProcessorImpl(port, currency)
```

```python
def create_checkout(api_key: str) -> Checkout:
    order_processor = OrderProcessorImpl(create_stripe_adapter(api_key), "GBP") # Calls another module's constructor, so how an OrderProcessor is built is now known in two places.
    return CheckoutImpl(create_order_processor_adapter(order_processor))
```

Good examples:

```python
def create_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    return OrderProcessorImpl(create_stripe_adapter(api_key), currency) # The adapter comes from its factory
```

```python
def create_checkout(api_key: str) -> Checkout:
    order_processor = create_stripe_order_processor(api_key, "GBP") # Another module's factory
    return CheckoutImpl(create_order_processor_adapter(order_processor))
```

```python
def create_checkout(order_processor: OrderProcessor) -> Checkout: # The entity is taken as a parameter
    return CheckoutImpl(create_order_processor_adapter(order_processor))
```
