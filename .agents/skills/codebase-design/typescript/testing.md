# Testing in TypeScript

The sections in [testing.md](../testing.md) are language-agnostic. This file is its TypeScript spelling. The vocabulary's TypeScript shapes — interfaces, function types, object literals — live in [typescript/codebase-design.md](codebase-design.md).

## What makes a good test

We will look at a good test for an `OrderProcessor` component. Consider the setup:

```ts
interface Payments { // The interface of the payments port
  charge(amount: number, currency: Currency): boolean;
}

type Clock = () => number; // The interface of the clock port: milliseconds since the epoch

type OrderProcessor = (order: Order) => Receipt;

function newOrderProcessor(
  payments: Payments, // A port, passed to the constructor
  clock: Clock, // A port, passed to the constructor
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

The fake for the payments port — a working fake, no mock library:

```ts
// tests/unit/components/order-processor/fakes.ts
interface FakePayments extends Payments { // a fake: decides what comes in, records what goes out
  charges: [number, Currency][];
}

function newFakePayments(accepts = true): FakePayments {
  const charges: [number, Currency][] = [];
  return {
    charges,
    charge(amount, currency) {          // satisfies the port by shape; the `extends` is a reminder of which one
      charges.push([amount, currency]); // records what goes out through the port
      return accepts;                   // decides what comes in
    },
  };
}
```

The clock's port is a function, so its fake is a function too: `() => NOON`.

The test:

```ts
// tests/unit/components/order-processor/order-processor.test.ts
import { expect, test } from "vitest";

const NOON = Date.UTC(2026, 0, 1, 12);

function orderWith(costs: number[]): Order { // a harness helper: construction lives in the kit, not the test
  return {
    id: "order_id",
    items: costs.map((cost, i) => ({ name: `item_${i}`, cost })),
  };
}

function setup({
  payments = newFakePayments(),
  clock = () => NOON,
  currency = "GBP",
}: { payments?: Payments; clock?: Clock; currency?: Currency } = {}): OrderProcessor { // Use a helper to wrap the component constructor so future changes to the constructor design can be localised in the test file
  return newOrderProcessor(payments, clock, currency);
}

test.each([
  { costs: [100], expectedCharge: 100 },      // worked examples, chosen by hand
  { costs: [100, 40], expectedCharge: 140 },
])("charges the payments port the order total ($costs)", ({ costs, expectedCharge }) => {
  const payments = newFakePayments();                     // the fake for the port this behaviour touches
  const orderProcessor = setup({ payments });             // constructed through the constructor, never a factory
  orderProcessor(orderWith(costs));                       // driven through the interface
  expect(payments.charges).toEqual([[expectedCharge, "GBP"]]); // the outcome goes out through the port — seen by the fake that receives it
});

test("stamps the receipt with the time from the clock", () => {
  const orderProcessor = setup({ clock: () => NOON });    // only the clock's fake matters to this behaviour
  expect(orderProcessor(orderWith([100])).at).toEqual(NOON);
});
```

- The name is the behaviour, and the assertions verify exactly it — a name promising one behaviour while the assertions check another is a test carrying two behaviours.
- Each `test.each` case is one condition of the one behaviour: a second condition is a second case, not a second assertion.
- The expected charges are worked examples (`100 + 40 = 140`, by hand) — the test never computes them with source code.
- Each port has its own fake, so a behaviour that touches one port is arranged through that fake alone, and the helper defaults the others.

An error the component determines is a behaviour, arranged through a fake and observed at the interface:

```ts
test("refuses an order the payments port declines", () => {
  const orderProcessor = setup({ payments: newFakePayments(false) });
  expect(() => orderProcessor(orderWith([100]))).toThrow(PaymentDeclined);
});
```

## Testing at the edge

### Adapters

An adapter is constructed with fakes of the interfaces of the components it calls, and driven through the port's interface it satisfies:

```ts
// tests/unit/adapters/checkout/payment/order-processor/order-processor.test.ts
function newFakeOrderProcessor() { // a fake of the interface the adapter takes: OrderProcessor
  const orders: Order[] = [];
  const orderProcessor: OrderProcessor = (order) => {
    orders.push(order);
    return { total: 140, currency: "GBP", at: NOON };
  };
  return { orderProcessor, orders };
}

test("pays for a cart by ordering each line", () => {
  const { orderProcessor, orders } = newFakeOrderProcessor();
  const payment = newOrderProcessorAdapter(orderProcessor); // the adapter's constructor, given a fake
  payment.pay({ id: "cart_id", lines: [{ product: "tea", price: 100 }, { product: "cake", price: 40 }] });
  expect(orders[0].items.map((item) => item.cost)).toEqual([100, 40]);
});
```

A decorator is constructed with a fake of the interface it wraps:

```ts
// tests/unit/adapters/order-processor/payments/limited/limited.test.ts
test("refuses a charge over the limit without calling the payments it wraps", () => {
  const inner = newFakePayments();
  const payments = newLimitedPayments(inner, 1_000);
  expect(payments.charge(1_001, "GBP")).toBe(false);
  expect(inner.charges).toEqual([]);
});
```

### Outbound edge components

A `WebhookReceipts` edge component that takes `undici`'s own `Dispatcher` is unit tested with the library's own test hook, `MockAgent`: a real dispatcher that answers from a function, with no network:

```ts
import type { Dispatcher } from "undici";

function newWebhookReceipts(dispatcher: Dispatcher, origin: string): Receipts { // everything required to measure its behaviours
  return {
    async announce(receipt) { /* dispatcher.request({ origin, path: "/receipts", method: "POST", body }) */ },
  };
}
```

```ts
import { MockAgent, type Dispatcher } from "undici";

function dispatcherAnswering(status: number, sent: string[]): Dispatcher { // harness: a dispatcher on the library's test hook
  const agent = new MockAgent();
  agent.disableNetConnect();                     // a request nothing answers fails, rather than reaching the network
  agent
    .get("https://hooks.example.com")
    .intercept({ path: "/receipts", method: "POST" })
    .reply(({ body }) => {
      sent.push(String(body));                   // records what goes out
      return { statusCode: status };             // decides what comes in
    });
  return agent;
}

test("announces each receipt to the webhook as JSON", async () => {
  const sent: string[] = [];
  const receipts = newWebhookReceipts(dispatcherAnswering(200, sent), "https://hooks.example.com");
  await receipts.announce({ total: 100, currency: "GBP", at: NOON }); // driven through its interface
  expect(JSON.parse(sent[0]).total).toBe(100);
});
```

Where a library offers no test hook, the edge component declares a view of the part of it that it uses, and the test passes a fake of the view. The `StripePayments` edge component calls the `sync-fetch` library, which has none, so it declares a view of the one function it uses; the library's default export satisfies it by shape:

```ts
// src/components/stripe-payments/views.ts
type SyncFetch = (url: string, init: { method: string; headers: Record<string, string>; body: string }) => { status: number }; // a view

function newStripePayments(fetch: SyncFetch, apiKey: string): Payments { // everything required to measure its behaviours
  return {
    charge(amount, currency) { /* ... */ },
  };
}
```

```ts
// tests/unit/components/stripe-payments/stripe-payments.test.ts
function newFakeFetch(status = 200) { // a fake of the view
  const bodies: URLSearchParams[] = [];
  const fetch: SyncFetch = (url, init) => {
    bodies.push(new URLSearchParams(init.body)); // records what goes out
    return { status };                           // decides what comes in
  };
  return { fetch, bodies };
}

test("charge sends the currency in lower case", () => {
  const { fetch, bodies } = newFakeFetch();
  const stripe = newStripePayments(fetch, "test-key");
  stripe.charge(1250, "GBP");                    // driven through its interface
  expect(bodies[0].get("currency")).toBe("gbp");
});

test("charge answers false when the card is declined", () => {
  const stripe = newStripePayments(newFakeFetch(402).fetch, "test-key");
  expect(stripe.charge(1250, "GBP")).toBe(false);
});
```

### A component that opens sessions

A lifecycle is tested the way a caller uses it, through the opening call. The session the realtime model opens is `AsyncDisposable`, so a caller holds it with `await using`, and leaving the block closes it. The SDK's realtime connection has no test hook, so the edge component declares a view of it, and the test passes a fake:

```ts
interface FakeConnection extends RealtimeConnection { // a fake of the RealtimeConnection view
  sent: RealtimeClientEvent[];
  closed: boolean;
}

function newFakeConnection(): FakeConnection {
  const connection: FakeConnection = {
    sent: [],
    closed: false,
    send(event) {
      connection.sent.push(event);               // records what goes out
    },
    close() {
      connection.closed = true;
    },
  };
  return connection;
}

function fakeConnect(connection: FakeConnection): Connect { // a fake of the Connect view
  return async () => connection;
}

test("a session sends each event it is given", async () => {
  const connection = newFakeConnection();
  const model = newOpenAIRealtimeModel(fakeConnect(connection), "gpt-realtime");
  {
    await using session = await model.connect();
    session.send(SPEAK_HELLO);
  }
  expect(connection.sent).toEqual([SPEAK_HELLO_EVENT]);
});

test("closing the session closes the connection", async () => {
  const connection = newFakeConnection();
  const model = newOpenAIRealtimeModel(fakeConnect(connection), "gpt-realtime");
  {
    await using session = await model.connect();
  }
  expect(connection.closed).toBe(true);
});
```

### Inbound edge components

An inbound edge component is driven the way its framework calls it. Fastify's `inject` sends a request to the app in-process, without opening a socket, so the test is a unit test. The router is built by its constructor with a fake for its port, never by its factory:

```ts
// tests/unit/components/orders-router/orders-router.test.ts
import Fastify, { type FastifyInstance, type FastifyPluginAsync } from "fastify";

function newFakePlaceOrder(placed: Placed | undefined) { // a fake for the router's placeOrder port
  const orders: NewOrder[] = [];
  const placeOrder: PlaceOrder = (newOrder) => {
    orders.push(newOrder);
    return placed;
  };
  return { placeOrder, orders };
}

function clientFor(router: FastifyPluginAsync): FastifyInstance { // harness: registers the router as the entrypoint would
  const app = Fastify();
  app.register(router);
  return app;
}

test("reads each cost into the new order", async () => {
  const { placeOrder, orders } = newFakePlaceOrder({ total: 140, currency: "GBP" });
  await clientFor(newOrdersRouter(placeOrder)).inject({ method: "POST", url: "/orders", payload: { id: "order_id", costs: [100, 40] } });
  expect(orders[0].costs).toEqual([100, 40]);
});

test("answers 402 when the order is declined", async () => {
  const response = await clientFor(newOrdersRouter(newFakePlaceOrder(undefined).placeOrder))
    .inject({ method: "POST", url: "/orders", payload: { id: "order_id", costs: [100] } });
  expect(response.statusCode).toBe(402);
});
```

A command that Node runs has no test client: the entrypoint calls it with `process.argv` and `process.stdout`. So the component declares a view of what it is called with, and the test calls it through the view, with a fake of the output:

```ts
// src/components/orders-cli/views.ts
interface Output { write(text: string): unknown }                    // a view: process.stdout satisfies it by shape
type Command = (argv: readonly string[], stdout: Output) => number;   // a view: what the entrypoint calls, answering an exit code
```

```ts
// tests/unit/components/orders-cli/orders-cli.test.ts
// newFakePlaceOrder: this component's own copy, beside these tests — fakes are duplicated, not shared

function newFakeOutput() { // a fake of the Output view
  const written: string[] = [];
  return { written, write: (text: string) => written.push(text) };
}

test("prints the total of the placed order", () => {
  const stdout = newFakeOutput();
  const command = newOrdersCli(newFakePlaceOrder({ total: 140, currency: "GBP" }).placeOrder);
  command(["order_id", "100", "40"], stdout);
  expect(stdout.written.join("")).toContain("total=140 GBP");
});
```

### Integration and end-to-end tests

Integration tests and end-to-end tests are kept apart from the unit tests by directory, so the default run needs no environment:

```ts
// tests/integration/components/postgres-orders/postgres-orders.test.ts
import pg from "pg";
import { afterAll, expect, test } from "vitest";

const pool = new pg.Pool({ connectionString: process.env.DATABASE_URL });
afterAll(() => pool.end());

test("saves and loads an order", async () => { // runs an edge component against the real resource
  const orders = newPostgresOrders(pool);
  await orders.save(orderWith([100]));
  expect((await orders.load("order_id")).items[0].cost).toBe(100);
});
```

```ts
// tests/e2e/cli.test.ts
test("cli processes an order", () => { // optional: runs an entrypoint with the production factories
  const output = execFileSync("tsx", ["src/entrypoints/cli.ts", "order_id", "100"], { encoding: "utf8" });
  expect(output).toContain("total=100");
});
```

```json
// package.json
{
  "scripts": {
    "test": "vitest run tests/unit",
    "test:integration": "vitest run tests/integration",
    "test:e2e": "vitest run tests/e2e"
  }
}
```

## Anti-patterns

**Tautological** — the oracle is the source code:

```ts
import { calculateTotal } from "../../../../src/components/order-processor/implementation"; // a source-code helper

test("totals the receipt", () => { // tautological
  const orderProcessor = setup();
  const order = orderWith([100, 40]);
  expect(orderProcessor(order).total).toBe(calculateTotal(order));
  // whatever bug calculateTotal carries, the expectation inherits —
  // the test agrees by construction and can never disagree
});
```

The fix is an oracle independent of the source code: computing the expectation in the test from the input is fine (`costs.reduce((sum, cost) => sum + cost, 0)`); the strongest form is the hand-picked worked examples above.

**Implementation-coupled** — mocking the implementation's internals:

```ts
import { expect, test, vi } from "vitest";
import { sumCosts } from "../../../../src/components/order-processor/totals"; // a helper the implementation calls internally

vi.mock("../../../../src/components/order-processor/totals");                 // reaches inside the implementation

test("sums the costs", () => {
  const orderProcessor = setup();
  vi.mocked(sumCosts).mockReturnValue(100);
  orderProcessor(orderWith([100, 40]));
  expect(sumCosts).toHaveBeenCalledOnce();
});
```

The tell: swap `sumCosts` for a hand-rolled loop — behaviour unchanged, every interface-level test green — and this test goes red. It was never on the outside of the interface. The fix: observation belongs at the interface and the ports — the fake's `charges` — not inside the implementation's helpers. (Mocking a source file with `vi.mock` and exporting internals just so a test can reach them are this pattern's two common TypeScript shapes.)

**Faked foreign component** — a hand-written stand-in for a library that has a test hook:

```ts
const fakeDispatcher = {                         // agrees with what its author believed undici does
  async request() {
    return { statusCode: 200, body: { async dump() {} } };
  },
} as unknown as Dispatcher;                      // the cast is the tell: it satisfies a sliver of Dispatcher, not the whole

const receipts = newWebhookReceipts(fakeDispatcher, "https://hooks.example.com");
```

The fix: pass the library's own dispatcher on its test hook, `MockAgent`, as above. Declare a view and fake it only where the library has no hook, as `StripePayments` does for `sync-fetch`.
