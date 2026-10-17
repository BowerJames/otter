# Dependency Injection in Python

The rules in [dependency-injection.md](../dependency-injection.md) are language-agnostic. This file is their Python spelling. The vocabulary's Python shapes — Protocol and Callable mechanics — live in [python/codebase-design.md](codebase-design.md).

# The constructor

## Rule 1: a constructor takes the component's ports and its configuration

Bad examples for an `OrderProcessor` component:

```python
from components.stripe_payments import StripePaymentsImpl

class OrderProcessorImpl:
    def __init__(
        self,
        payments: StripePaymentsImpl # The constructor names an edge component's implementation.
    ): ...

    def __call__(self, order: Order) -> Receipt: ...
```

```python
from components.payment_gateway import PaymentGateway

class OrderProcessorImpl:
    def __init__(
        self,
        payments: PaymentGateway # The constructor names another component's interface, so a change to that component reaches this one.
    ): ...

    def __call__(self, order: Order) -> Receipt: ...
```

```python
class OrderProcessorPort(Protocol): # One port holding two dependencies: swapping payments now means touching the clock.
    def charge(self, amount: int, currency: Currency) -> bool: ...
    def now(self) -> datetime: ...

class OrderProcessorImpl:
    def __init__(self, port: OrderProcessorPort): ...
```

```python
class Payments(Protocol): # The port is copied from what Stripe offers, not from what the component calls.
    def charge(self, amount: int, currency: Currency) -> bool: ...
    def refund(self, amount: int, currency: Currency) -> bool: ...
    def list_charges(self) -> list[Charge]: ...
```

Good example for an `OrderProcessor` component:

```python
class Payments(Protocol): # The payments port's interface, declared by the component, holding only what it calls.
    def charge(self, amount: int, currency: Currency) -> bool: ...

type Clock = Callable[[], datetime] # The clock port's interface.

class OrderProcessorImpl:
    def __init__(
        self,
        payments: Payments, # A port: any component or adapter satisfying it can be passed.
        clock: Clock, # A second dependency, so a second port.
        currency: Currency # Configuration: a value, passed as its concrete type.
    ): ...

    def __call__(self, order: Order) -> Receipt: ...
```

A `Refunds` component that also needs Stripe declares its own port. Stripe's edge component can satisfy both if its interface has both methods, or each component's port can be satisfied by its own edge component:

```python
class RefundIssuer(Protocol): # The port of the refunds component
    def refund(self, amount: int, currency: Currency) -> bool: ...

class RefundsImpl:
    def __init__(self, issuer: RefundIssuer): ...
```

At the edge, an outbound edge component's constructor takes the library's own object, and like every constructor it must take everything required to measure the component's behaviours:

```python
class StripePaymentsImpl:
    def __init__(self, api_key: str):
        self.http = httpx.Client() # bad: created inside, so a test cannot measure what is sent
```

```python
class StripePaymentsImpl:
    def __init__(
        self,
        http: httpx.Client, # good: the library's own client, passed in, so a test can pass one on httpx.MockTransport and measure what is sent
        api_key: str
    ): ...
```

An adapter's constructor takes the interface of the component it calls, never a port's interface, unless it is a decorator of that port:

```python
class OrderProcessorAdapter: # adapters/checkout/payment/order_processor
    def __init__(self, order_processor: OrderProcessor): ... # good: the interface of the component it calls

class LimitedPayments: # adapters/order_processor/payments/limited
    def __init__(self, inner: Payments, limit: int): ... # good: a decorator takes the interface it satisfies

class StripeCheckoutAdapter:
    def __init__(self, http: httpx.Client): ... # bad: an adapter takes no foreign object; reaching Stripe is an edge component's work
```

## Rule 2: ports and configuration go in the constructor, not the interface

Avoid for an `OrderProcessor` component:

```python
type OrderProcessor = Callable[[Order, Payments], Receipt]

class OrderProcessorImpl:
    def __call__(
        self,
        order: Order,
        payments: Payments # The port that changes the capability of the order processor is in the interface, so every caller must supply it.
    ) -> Receipt:
        ...
```

Prefer for an `OrderProcessor` component:

```python
type OrderProcessor = Callable[[Order], Receipt]

class OrderProcessorImpl:
    def __init__(
        self,
        payments: Payments, # The port is passed to the constructor, so the interface takes only the order.
        clock: Clock,
        currency: Currency
    ):
        self.payments = payments
        self.clock = clock
        self.currency = currency

    def __call__(self, order: Order) -> Receipt:
        total = sum(item.cost for item in order.items)
        if not self.payments.charge(total, self.currency):
            raise PaymentDeclined(order.id)
        return Receipt(total=total, currency=self.currency, at=self.clock())
```

An inbound edge component's dependencies arrive the same way, never through the framework's own injection:

```python
def get_place_order() -> PlaceOrder: ...

def orders_router() -> APIRouter:
    router = APIRouter()

    @router.post("/orders")
    def create(body: OrderBody, place_order: PlaceOrder = Depends(get_place_order)) -> ReceiptBody: # bad: the dependency is fetched by FastAPI, so no constructor declares it
        ...

    return router
```

```python
def orders_router(place_order: PlaceOrder) -> APIRouter: # good: the port is declared in the constructor
    router = APIRouter()

    @router.post("/orders")
    def create(body: OrderBody, request: Request) -> ReceiptBody: # the request belongs to the foreign interface, used only here
        ...

    return router
```

## Rule 3: a constructor accepts what it needs, and reaches no resource

Avoid a constructor or implementation that creates or fetches what it needs:

```python
class OrderProcessorImpl:
    def __init__(self):
        api_key = os.environ["STRIPE_API_KEY"]   # fetches a resource
        self.payments = StripePaymentsImpl(httpx.Client(), api_key)  # creates another component
        self.currency = os.environ["CURRENCY"]   # fetches its own configuration

    def __call__(self, order: Order) -> Receipt:
        placed_at = datetime.now()               # fetches a resource
        ...
```

Prefer a constructor that accepts all of it, with the clock reached through its port:

```python
class OrderProcessorImpl:
    def __init__(self, payments: Payments, clock: Clock, currency: Currency):
        self.payments = payments
        self.clock = clock
        self.currency = currency

    def __call__(self, order: Order) -> Receipt:
        placed_at = self.clock()
        ...
```

An edge component's constructor stores what it is given. It reaches its resource only when called:

```python
class PostgresOrders:
    def __init__(self, dsn: str):
        self.connection = psycopg.connect(dsn) # bad: constructing the component opens a connection
```

```python
class PostgresOrders:
    def __init__(self, pool: ConnectionPool): # good: the pool lives as long as the process, so the entrypoint opened it
        self.pool = pool

    def save(self, order: Order) -> None:
        with self.pool.connection() as connection: # a connection for one use, taken when called
            ...
```

A resource that lives for one conversation is opened by the component that owns the conversation, through its interface:

```python
class OpenAIRealtimeModel:
    def __init__(self, connect: Connect, model_name: str): # Connect: a view of the SDK's client.realtime.connect
        self.open_connection = connect # reaches nothing
        self.model_name = model_name

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[RealtimeSession]:
        async with self.open_connection(model=self.model_name) as connection: # acquired when called
            yield OpenAIRealtimeSession(connection)
```

# The factory

The examples build on the `OrderProcessor` component above and two edge components that can satisfy its `payments` port, each with its factory:

```python
# factories/components/stripe_payments/factory.py
def create_stripe_payments(api_key: str) -> StripePayments: # A factory returns the interface
    return StripePaymentsImpl(httpx.Client(base_url="https://api.stripe.com"), api_key) # It builds the library objects the edge component takes

# factories/components/paypal_payments/factory.py
def create_paypal_payments(api_key: str) -> PaypalPayments:
    return PaypalPaymentsImpl(httpx.Client(base_url="https://api.paypal.com"), api_key)
```

## Rule 4: a factory returns the interface

Bad examples:

```python
def create_order_processor(
        provider: Literal["stripe", "paypal"],
        api_key: str,
        currency: Currency
    ) -> OrderProcessorImpl: # This is not a factory for the OrderProcessor component as it declares the return type as the implementation, not the interface.
    ...

def create_stripe_payments(api_key: str) -> StripePaymentsImpl: # The factory returns the edge component's implementation, not its interface.
    ...
```

Good example:

```python
def create_order_processor(
        provider: Literal["stripe", "paypal"],
        api_key: str,
        currency: Currency
    ) -> OrderProcessor: # A factory declares the component's interface as its return type.
    if provider == "stripe":
        payments = create_stripe_payments(api_key)
    elif provider == "paypal":
        payments = create_paypal_payments(api_key)
    return OrderProcessorImpl(payments, partial(datetime.now, UTC), currency)
```

An inbound edge component's factory returns the foreign interface it presents:

```python
def create_orders_router(order_processor: OrderProcessor) -> APIRouter:
    return orders_router(create_order_processor_adapter(order_processor))
```

## Rule 5: a factory only wires

Bad example:

```python
def create_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    order_processor = OrderProcessorImpl(create_stripe_payments(api_key), partial(datetime.now, UTC), currency)

    def with_retry(order: Order) -> Receipt: # Retrying is a behaviour, and no fake can reach it here.
        for _ in range(3):
            try:
                return order_processor(order)
            except ConnectionError:
                continue
        raise ...

    return with_retry
```

Retrying belongs behind a constructor: in `OrderProcessorImpl`, or in a decorator of the `payments` port. The factories then only choose and construct:

```python
# factories/adapters/order_processor/payments/retrying/factory.py
def create_retrying_payments(inner: Payments, attempts: int) -> Payments:
    return RetryingPayments(inner, attempts)
```

```python
def create_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    payments = create_retrying_payments(create_stripe_payments(api_key), attempts=3)
    return OrderProcessorImpl(payments, partial(datetime.now, UTC), currency)
```

## Rule 6: a factory reaches no resource

Bad examples:

```python
def create_stripe_payments() -> StripePayments:
    return StripePaymentsImpl(
        http=httpx.Client(),
        api_key=os.environ["STRIPE_API_KEY"] # The factory reads the environment.
    )
```

```python
def create_openai_model(model_id: str) -> ChatModel:
    return OpenAIModel(OpenAI(), model_id) # The SDK reads OPENAI_API_KEY from the environment on the factory's behalf.
```

Good examples, with the values passed in by whatever calls the factory:

```python
def create_stripe_payments(api_key: str) -> StripePayments:
    return StripePaymentsImpl(
        http=httpx.Client(), # Building reaches no resource: the client only reaches the network when called.
        api_key=api_key
    )

def create_openai_model(api_key: str, model_id: str) -> ChatModel:
    return OpenAIModel(OpenAI(api_key=api_key), model_id) # Every value the library would read from the environment is passed.
```

```python
# entrypoints/cli.py, or a settings loader: whichever the design chooses
order_processor = create_order_processor(
    api_key=os.environ["STRIPE_API_KEY"],
    currency="GBP"
)
```

A resource that lives as long as the process is opened outside the factories too, and passed in:

```python
def create_postgres_orders(pool: ConnectionPool) -> Orders:
    return PostgresOrders(pool)
```

```python
# entrypoints/fastapi.py
def main() -> None:
    with ConnectionPool(os.environ["DATABASE_URL"]) as pool: # acquired, and closed, by the entrypoint
        app = FastAPI()
        app.include_router(create_order_history_router(create_postgres_orders(pool)))
        uvicorn.run(app)
```

## Rule 7: one constructor, many factories

Each factory is one way of supplying the single constructor:

```python
def create_stripe_order_processor(api_key: str, currency: Currency) -> OrderProcessor:
    return OrderProcessorImpl(create_stripe_payments(api_key), partial(datetime.now, UTC), currency)

def create_in_memory_order_processor(currency: Currency, now: datetime) -> OrderProcessor:
    return OrderProcessorImpl(create_in_memory_payments(), lambda: now, currency)
```

Bad example, a second way of constructing added to the implementation:

```python
class OrderProcessorImpl:
    def __init__(self, payments: Payments, clock: Clock, currency: Currency): ...

    @classmethod
    def with_stripe(cls, api_key: str) -> "OrderProcessorImpl": # A second constructor: the implementation now knows about an edge component.
        return cls(StripePaymentsImpl(httpx.Client(), api_key), datetime.now, "GBP")
```

## Rule 8: a composite is a factory

A research team presents a researcher, its search and its memory as one `Agent`. Its parameter is its one port, the model; everything else is built inside and hidden:

```python
# factories/components/researcher/research_team.py
def create_research_team(model: ChatModel, search_api_key: str) -> Agent: # A composite: its ports are its parameters, and it returns one interface
    return ResearcherImpl(
        model=model, # the composite's port, passed to the component inside
        search=create_web_search(search_api_key),
        memory=create_in_memory_notes(),
    )
```

A lead agent takes two research teams as tools, without knowing what they are made of:

```python
def create_lead(model: ChatModel, search_api_key: str) -> Agent:
    teams = [create_research_team(model, search_api_key) for _ in range(2)]
    return LeadImpl(model=model, subagents=[create_agent_tool(team) for team in teams])
```

Bad example, a composite with behaviour of its own:

```python
def create_research_team(model: ChatModel, search_api_key: str) -> Agent:
    researcher = ResearcherImpl(model, create_web_search(search_api_key), create_in_memory_notes())

    def run(task: str) -> str: # Truncating is a behaviour, and no fake can reach it here: it belongs in a component.
        return researcher.run(task)[:500]

    return run
```
