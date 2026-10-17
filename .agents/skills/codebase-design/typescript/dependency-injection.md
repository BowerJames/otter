# Dependency Injection in TypeScript

The rules in [dependency-injection.md](../dependency-injection.md) are language-agnostic. This file is their TypeScript spelling. The vocabulary's TypeScript shapes — interfaces, function types, object literals — live in [typescript/codebase-design.md](codebase-design.md).

The style throughout: **no classes**. Entities are functions and object literals returned by their constructors; they satisfy an `interface` structurally. The one exception is an error: a subclass of `Error`. A constructor is `new…` (`newOrderProcessor`); a factory is `create…` (`createOrderProcessor`).

# The constructor

## Rule 1: a constructor takes the component's ports and its configuration

Bad examples for an `OrderProcessor` component:

```ts
import { newStripePayments } from "../stripe-payments";

function newOrderProcessor(
  payments: ReturnType<typeof newStripePayments>, // The constructor names an edge component's constructor, so the port is whatever its implementation returns.
): OrderProcessor {
  /* ... */
}
```

```ts
import type { PaymentGateway } from "../payment-gateway";

function newOrderProcessor(
  payments: PaymentGateway, // The constructor names another component's interface, so a change to that component reaches this one.
): OrderProcessor {
  /* ... */
}
```

```ts
interface OrderProcessorPort { // One port holding two dependencies: swapping payments now means touching the clock.
  charge(amount: number, currency: Currency): boolean;
  now(): number;
}

function newOrderProcessor(port: OrderProcessorPort): OrderProcessor {
  /* ... */
}
```

```ts
interface Payments { // The port is copied from what Stripe offers, not from what the component calls.
  charge(amount: number, currency: Currency): boolean;
  refund(amount: number, currency: Currency): boolean;
  listCharges(): Charge[];
}
```

Good example for an `OrderProcessor` component:

```ts
interface Payments { // The payments port's interface, declared by the component, holding only what it calls.
  charge(amount: number, currency: Currency): boolean;
}

type Clock = () => number; // The clock port's interface: milliseconds since the epoch.

function newOrderProcessor(
  payments: Payments, // A port: any component or adapter satisfying it can be passed.
  clock: Clock,       // A second dependency, so a second port.
  currency: Currency, // Configuration: a value, passed as its concrete type.
): OrderProcessor {
  /* ... */
}
```

A `Refunds` component that also needs Stripe declares its own port. Stripe's edge component can satisfy both if its interface has both methods, or each component's port can be satisfied by its own edge component:

```ts
interface RefundIssuer { // The port of the refunds component
  refund(amount: number, currency: Currency): boolean;
}

function newRefunds(issuer: RefundIssuer): Refunds {
  /* ... */
}
```

At the edge, an outbound edge component's constructor takes the library's own object, typed by a view where the library offers no test hook, and like every constructor it must take everything required to measure the component's behaviours:

```ts
import syncFetch from "sync-fetch";

function newStripePayments(apiKey: string): StripePayments {
  const fetch = syncFetch; // bad: the library reached directly, so a test cannot measure what is sent
  /* ... */
}
```

```ts
function newStripePayments(
  fetch: SyncFetch, // good: the library's function, passed in and typed by a view since sync-fetch has no test hook, so a test can pass a fake and measure what is sent
  apiKey: string,
): StripePayments {
  /* ... */
}
```

An adapter's constructor takes the interface of the component it calls, never a port's interface, unless it is a decorator of that port:

```ts
// adapters/checkout/payment/order-processor
function newOrderProcessorAdapter(orderProcessor: OrderProcessor): Payment { /* ... */ } // good: the interface of the component it calls

// adapters/order-processor/payments/limited
function newLimitedPayments(inner: Payments, limit: number): Payments { /* ... */ } // good: a decorator takes the interface it satisfies

function newStripeCheckoutAdapter(fetch: SyncFetch): Payment { /* ... */ } // bad: an adapter takes no foreign object; reaching Stripe is an edge component's work
```

## Rule 2: ports and configuration go in the constructor, not the interface

Avoid for an `OrderProcessor` component:

```ts
type OrderProcessor = (order: Order, payments: Payments) => Receipt;

function newOrderProcessor(): OrderProcessor {
  return function processOrder(
    order,
    payments, // The port that changes the capability of the order processor is in the interface, so every caller must supply it.
  ) {
    /* ... */
  };
}
```

Prefer for an `OrderProcessor` component:

```ts
type OrderProcessor = (order: Order) => Receipt;

function newOrderProcessor(
  payments: Payments, // The port is passed to the constructor, so the interface takes only the order.
  clock: Clock,
  currency: Currency,
): OrderProcessor {
  return function processOrder(order) {
    const total = order.items.reduce((sum, item) => sum + item.cost, 0);
    if (!payments.charge(total, currency)) {
      throw new PaymentDeclined(order.id);
    }
    return { total, currency, at: clock() };
  };
}
```

An inbound edge component's dependencies arrive the same way, never through the framework's own injection:

```ts
// entrypoints/server.ts
app.decorate("placeOrder", createPlaceOrder());
```

```ts
function newOrdersRouter(): FastifyPluginAsync {
  return async (app) => {
    app.post<{ Body: OrderBody }>("/orders", async (request, reply) => {
      const placed = app.placeOrder(toNewOrder(request.body)); // bad: the dependency is fetched from what Fastify was decorated with, so no constructor declares it
      /* ... */
    });
  };
}
```

```ts
function newOrdersRouter(placeOrder: PlaceOrder): FastifyPluginAsync { // good: the port is declared in the constructor
  return async (app) => {
    app.post<{ Body: OrderBody }>("/orders", async (request, reply) => { // the request and reply belong to the foreign interface, used only here
      /* ... */
    });
  };
}
```

## Rule 3: a constructor accepts what it needs, and reaches no resource

Avoid a constructor or implementation that creates or fetches what it needs:

```ts
function newOrderProcessor(): OrderProcessor {
  const apiKey = process.env.STRIPE_API_KEY!;               // fetches a resource
  const payments = newStripePayments(syncFetch, apiKey);    // creates another component
  const currency = process.env.CURRENCY as Currency;        // fetches its own configuration
  return function processOrder(order) {
    const placedAt = Date.now();                            // fetches a resource
    /* ... */
  };
}
```

Prefer a constructor that accepts all of it, with the clock reached through its port:

```ts
function newOrderProcessor(payments: Payments, clock: Clock, currency: Currency): OrderProcessor {
  return function processOrder(order) {
    const placedAt = clock();
    /* ... */
  };
}
```

An edge component's constructor keeps what it is given. It reaches its resource only when called:

```ts
function newPostgresOrders(connectionString: string): Orders {
  const client = new Client({ connectionString });
  void client.connect(); // bad: constructing the component opens a connection
  /* ... */
}
```

```ts
function newPostgresOrders(pool: Pool): Orders { // good: the pool lives as long as the process, so the entrypoint opened it
  return {
    async save(order) {
      const client = await pool.connect(); // a connection for one use, taken when called
      try {
        /* ... */
      } finally {
        client.release();
      }
    },
  };
}
```

A resource that lives for one conversation is opened by the component that owns the conversation, through its interface:

```ts
function newOpenAIRealtimeModel(
  openConnection: Connect, // Connect: a view of opening the SDK's realtime connection
  modelName: string,
): RealtimeModel {
  return { // reaches nothing
    async connect() {
      const connection = await openConnection({ model: modelName }); // acquired when called
      return newOpenAIRealtimeSession(connection); // the session holds the connection, and closes it when disposed
    },
  };
}
```

Whoever owns the conversation opens it, and the session is closed when it goes out of scope: `await using session = await model.connect();`.

# The factory

The examples build on the `OrderProcessor` component above and two edge components that can satisfy its `payments` port, each with its factory:

```ts
// factories/components/stripe-payments/factory.ts
function createStripePayments(apiKey: string): StripePayments { // A factory returns the interface
  return newStripePayments(syncFetch, apiKey); // It passes the library objects the edge component takes
}

// factories/components/paypal-payments/factory.ts
function createPaypalPayments(apiKey: string): PaypalPayments {
  return newPaypalPayments(syncFetch, apiKey);
}
```

## Rule 4: a factory returns the interface

Bad examples:

```ts
function createOrderProcessor(
  provider: "stripe" | "paypal",
  apiKey: string,
  currency: Currency,
) { // This is not a factory for the OrderProcessor component: with no declared return type, callers get whatever shape the implementation happens to return, not a promise of the component's interface.
  /* ... */
}

function createStripePayments(apiKey: string) { // The factory declares no return type, so callers see the edge component's implementation, not its interface.
  /* ... */
}
```

Good example:

```ts
function createOrderProcessor(
  provider: "stripe" | "paypal",
  apiKey: string,
  currency: Currency,
): OrderProcessor { // A factory declares the component's interface as its return type.
  const payments = provider === "stripe" ? createStripePayments(apiKey) : createPaypalPayments(apiKey);
  return newOrderProcessor(payments, Date.now, currency);
}
```

An inbound edge component's factory returns the foreign interface it presents:

```ts
function createOrdersRouter(orderProcessor: OrderProcessor): FastifyPluginAsync {
  return newOrdersRouter(createOrderProcessorAdapter(orderProcessor));
}
```

## Rule 5: a factory only wires

Bad example:

```ts
function createOrderProcessor(apiKey: string, currency: Currency): OrderProcessor {
  const orderProcessor = newOrderProcessor(createStripePayments(apiKey), Date.now, currency);

  return function withRetry(order) { // Retrying is a behaviour, and no fake can reach it here.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        return orderProcessor(order);
      } catch {
        continue;
      }
    }
    throw new Error(/* ... */);
  };
}
```

Retrying belongs behind a constructor: in the order processor's implementation, or in a decorator of the `payments` port. The factories then only choose and construct:

```ts
// factories/adapters/order-processor/payments/retrying/factory.ts
function createRetryingPayments(inner: Payments, attempts: number): Payments {
  return newRetryingPayments(inner, attempts);
}
```

```ts
function createOrderProcessor(apiKey: string, currency: Currency): OrderProcessor {
  const payments = createRetryingPayments(createStripePayments(apiKey), 3);
  return newOrderProcessor(payments, Date.now, currency);
}
```

## Rule 6: a factory reaches no resource

Bad examples:

```ts
function createStripePayments(): StripePayments {
  return newStripePayments(
    syncFetch,
    process.env.STRIPE_API_KEY!, // The factory reads the environment.
  );
}
```

```ts
function createOpenAIModel(modelId: string): ChatModel {
  return newOpenAIModel(new OpenAI(), modelId); // The SDK reads OPENAI_API_KEY from the environment on the factory's behalf.
}
```

Good examples, with the values passed in by whatever calls the factory:

```ts
function createStripePayments(apiKey: string): StripePayments {
  return newStripePayments(
    syncFetch, // Passing the library's function reaches no resource: it only reaches the network when called.
    apiKey,
  );
}

function createOpenAIModel(apiKey: string, modelId: string): ChatModel {
  return newOpenAIModel(new OpenAI({ apiKey }), modelId); // Every value the library would read from the environment is passed.
}
```

```ts
// entrypoints/cli.ts, or a settings loader: whichever the design chooses
const orderProcessor = createOrderProcessor(process.env.STRIPE_API_KEY!, "GBP");
```

A resource that lives as long as the process is opened outside the factories too, and passed in:

```ts
function createPostgresOrders(pool: Pool): Orders {
  return newPostgresOrders(pool);
}
```

```ts
// entrypoints/server.ts
const pool = new Pool({ connectionString: process.env.DATABASE_URL }); // acquired, and closed, by the entrypoint
const app = Fastify();
app.register(createOrderHistoryRouter(createPostgresOrders(pool)));
app.addHook("onClose", () => pool.end());
await app.listen({ port: 3000 });
```

## Rule 7: one constructor, many factories

Each factory is one way of supplying the single constructor:

```ts
function createStripeOrderProcessor(apiKey: string, currency: Currency): OrderProcessor {
  return newOrderProcessor(createStripePayments(apiKey), Date.now, currency);
}

function createInMemoryOrderProcessor(currency: Currency, now: number): OrderProcessor {
  return newOrderProcessor(createInMemoryPayments(), () => now, currency);
}
```

Bad example, a second way of constructing added beside the implementation:

```ts
// components/order-processor/implementation.ts
export function newOrderProcessor(payments: Payments, clock: Clock, currency: Currency): OrderProcessor { /* ... */ }

export function newStripeOrderProcessor(apiKey: string): OrderProcessor { // A second constructor: the component now knows about an edge component.
  return newOrderProcessor(newStripePayments(syncFetch, apiKey), Date.now, "GBP");
}
```

## Rule 8: a composite is a factory

A research team presents a researcher, its search and its memory as one `Agent`. Its parameter is its one port, the model; everything else is built inside and hidden:

```ts
// factories/components/researcher/research-team.ts
function createResearchTeam(model: ChatModel, searchApiKey: string): Agent { // A composite: its ports are its parameters, and it returns one interface
  return newResearcher(
    model, // the composite's port, passed to the component inside
    createWebSearch(searchApiKey),
    createInMemoryNotes(),
  );
}
```

A lead agent takes two research teams as tools, without knowing what they are made of:

```ts
function createLead(model: ChatModel, searchApiKey: string): Agent {
  const teams = [createResearchTeam(model, searchApiKey), createResearchTeam(model, searchApiKey)];
  return newLead(model, teams.map((team) => createAgentTool(team)));
}
```

Bad example, a composite with behaviour of its own:

```ts
function createResearchTeam(model: ChatModel, searchApiKey: string): Agent {
  const researcher = newResearcher(model, createWebSearch(searchApiKey), createInMemoryNotes());

  return {
    async run(task) { // Truncating is a behaviour, and no fake can reach it here: it belongs in a component.
      return (await researcher.run(task)).slice(0, 500);
    },
  };
}
```
