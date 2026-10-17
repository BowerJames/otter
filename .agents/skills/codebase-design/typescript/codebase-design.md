# Codebase Design in TypeScript

The vocabulary in [SKILL.md](../SKILL.md) is language-agnostic. This file is its TypeScript spelling.

The style throughout: **no classes**. Entities are functions and object literals returned by their constructors; they satisfy an `interface` structurally. The one exception is an error: a subclass of `Error`.

## Vocabulary → TypeScript

| Term | TypeScript |
|---|---|
| **Interface** | for object shapes, an `interface`; for functions, a type — `(order: Order) => Receipt` |
| **Port** | a parameter of the constructor, named for the dependency and typed by an `interface` or a function type — `payments: Payments`, `clock: Clock` |
| **Adapter** | an object literal or function satisfying a port's or a contract's shape, returned by a constructor that takes the interfaces of the components it calls |
| **Decorator** | an adapter whose constructor takes the interface it satisfies — `newLimitedPayments(inner: Payments, limit: number): Payments` |
| **Contract** | an `interface` or a data carrier in the contracts package — `AgentTool`, `Currency` |
| **Foreign component** | a library, framework or runtime — `sync-fetch`, the OpenAI SDK, Fastify, Commander, the `node:` built-ins, Node running a file |
| **Outbound edge component** | a component whose constructor takes a library's own object, or a view of it — `newStripePayments(fetch: SyncFetch, …)` |
| **Inbound edge component** | a component whose interface is a framework's shape — a constructor returning a Fastify plugin (`FastifyPluginAsync`) or a Commander `Command` |
| **View** | an `interface` or `type` in an edge component's package, describing the part of a foreign interface it touches — needed only when the library has no test hook (Fastify has one: `app.inject`; `sync-fetch` and a websocket connection have none) |
| **Entrypoint** | a file the outside world is pointed at — a `bin` script in `package.json`, the file `node` runs to build a Fastify app and call `listen` |
| **Constructor** | the function that takes the ports and configuration and returns the entity |
| **Data carrier** | an `interface` or `type` of plain, `readonly` data, or a union of literals |
| **Error** | a subclass of `Error` |

With no classes, a constructor and a factory are both functions. They are told apart by name: a constructor is `new…` (`newOrderProcessor`), a factory is `create…` (`createOrderProcessor`).

## Component

Below illustrates an example of an `OrderProcessor` component in TypeScript.

The interface of a component can be spelled as an `interface` or as a type. Both of the below define the same interface; pick one.

```ts
interface OrderProcessor { // Interface for the component, as an interface
  (order: Order): Receipt;
}
```

```ts
type OrderProcessor = (order: Order) => Receipt; // Interface for the component, as a type
```

The rest of the component is the same whichever spelling is used. It has two dependencies, so it has two ports:

```ts
import type { Currency } from "../../contracts/currency"; // A contract: Currency means the same thing to every component

export interface Payments { // The interface of the payments port: only what the component calls
  charge(amount: number, currency: Currency): boolean;
}

export type Clock = () => number; // The interface of the clock port: milliseconds since the epoch

export class PaymentDeclined extends Error {} // An error the component's implementation determines, so the component owns it

export function newOrderProcessor(
  payments: Payments, // a port
  clock: Clock,       // a port
  currency: Currency, // configuration
): OrderProcessor { // Constructor for the component
  return function processOrder(order) { // Implementation of the component
    const total = order.items.reduce((sum, item) => sum + item.cost, 0);
    if (!payments.charge(total, currency)) {
      throw new PaymentDeclined(order.id);
    }
    return { total, currency, at: clock() };
  };
}
```

Each port is satisfied, swapped and faked on its own: a test can fix the clock without touching payments, and a new payment provider never touches the clock.

## Outbound edge component

`StripePayments` is a component of its own: it faces Stripe's HTTP API, a foreign component. Its constructor takes the library's own object. The `sync-fetch` library offers no test hook, so the component declares a view of the one function it uses: the library's default export satisfies it by shape, and a test passes a fake:

```ts
import type { Currency } from "../../contracts/currency";

export type SyncFetch = ( // A view, in components/stripe-payments/views.ts: the part of sync-fetch the component uses
  url: string,
  init: { method: string; headers: Record<string, string>; body: string },
) => { status: number };

export interface StripePayments { // Interface for the edge component
  charge(amount: number, currency: Currency): boolean;
}

export function newStripePayments(
  fetch: SyncFetch, // the library's own function, typed by its view: its foreign dependency
  apiKey: string,   // configuration
): StripePayments { // An outbound edge component
  return {
    charge(amount, currency) {
      const response = fetch("https://api.stripe.com/v1/charges", { // humble shell
        method: "POST",
        headers: { authorization: `Bearer ${apiKey}`, "content-type": "application/json" },
        body: toChargeBody(amount, currency),
      });
      return charged(response.status);
    },
  };
}

function toChargeBody(amount: number, currency: Currency): string { // translation: a plain function
  return JSON.stringify({ amount, currency: currency.toLowerCase() });
}

function charged(status: number): boolean {
  return status !== 402;
}
```

Its interface satisfies the `payments` port as it is, so a factory passes it straight to the port: there is no adapter. Matching is structural: anything with a matching `charge` satisfies `Payments`, and the declared return type checks each object literal where it is built, so drift is a compile error at that point. No `class` and no `implements` are needed. The clock's port is satisfied by the runtime's own function, which already has its shape:

```ts
import syncFetch from "sync-fetch";

function createStripePayments(apiKey: string): StripePayments { // A factory for the edge component
  return newStripePayments(syncFetch, apiKey);
}

function createOrderProcessor(apiKey: string, currency: Currency): OrderProcessor { // A factory for the order processor
  return newOrderProcessor(
    createStripePayments(apiKey), // a component passed directly to a port
    Date.now,                     // a foreign object that already has the port's shape
    currency,                     // configuration
  );
}
```

Passing `syncFetch` reaches no resource: it sends a request only when it is called. A factory passes every value a library would otherwise read from the environment, such as an API key, as a parameter.

## Decorator

A decorator wraps the interface it satisfies. `newLimitedPayments` refuses any charge over a configured limit, and passes every other charge to the payments it wraps:

```ts
function newLimitedPayments(
  inner: Payments, // Takes the interface it satisfies
  limit: number,   // configuration
): Payments { // A decorator for the payments port
  return {
    charge(amount, currency) {
      if (amount > limit) {
        return false;
      }
      return inner.charge(amount, currency);
    },
  };
}
```

A factory combines them at runtime: `newLimitedPayments(createStripePayments(apiKey), 10_000)`. Neither imports the other.

An adapter's constructor declares the interface it satisfies as its return type (`: Payments`). The return type is a reminder, not a requirement of structural matching: it links the adapter to the port it is intended for, so a developer reading the adapter can see the dependency, and the compiler checks the object literal against it.

## Inbound edge component

The orders router is called by Fastify, so its interface is foreign: the plugin Fastify registers. Its port is the project's own, and the translation between HTTP bodies and its data carriers is plain functions:

```ts
import type { FastifyPluginAsync } from "fastify";

export type PlaceOrder = (newOrder: NewOrder) => Placed | undefined; // The interface of its port: undefined means the payment was declined

interface OrderBody { // Part of the foreign interface: the shape Fastify parses a request body into
  readonly id: string;
  readonly costs: readonly number[];
}

interface ReceiptBody {
  readonly total: number;
  readonly currency: string;
}

const orderBodySchema = { // Part of the foreign interface: Fastify validates requests against JSON Schema
  type: "object",
  required: ["id", "costs"],
  properties: { id: { type: "string" }, costs: { type: "array", items: { type: "integer" } } },
} as const;

export function newOrdersRouter(placeOrder: PlaceOrder): FastifyPluginAsync { // Constructor: its interface is foreign
  return async (app) => {
    app.post<{ Body: OrderBody }>("/orders", { schema: { body: orderBodySchema } }, async (request, reply) => { // humble shell
      const placed = placeOrder(toNewOrder(request.body));
      if (placed === undefined) {
        return reply.code(402).send({ error: "payment declined" }); // handled: 402 is the answer
      }
      return reply.code(201).send(toBody(placed));
    });
  };
}

function toNewOrder(body: OrderBody): NewOrder { // translation: plain functions
  return { id: body.id, costs: body.costs };
}

function toBody(placed: Placed): ReceiptBody {
  return { total: placed.total, currency: placed.currency };
}
```

`NewOrder` and `Placed` are the router's own data carriers. The router never imports the order processor: an adapter satisfies `placeOrder` by calling it, translating its data carriers and handling its `PaymentDeclined` as `undefined`:

```ts
import { PaymentDeclined, type Order, type OrderProcessor, type Receipt } from "../../../../components/order-processor";
import type { PlaceOrder } from "../../../../components/orders-router";

// adapters/orders-router/place-order/order-processor
export function newOrderProcessorAdapter(orderProcessor: OrderProcessor): PlaceOrder { // Takes the interface of the component it calls
  return function placeOrder(newOrder) {
    const order: Order = { id: newOrder.id, items: newOrder.costs.map((cost, i) => ({ name: `item_${i}`, cost })) };
    let receipt: Receipt;
    try {
      receipt = orderProcessor(order);
    } catch (error) {
      if (error instanceof PaymentDeclined) {
        return undefined; // handled: a decline is an answer the port can give
      }
      throw error; // anything else propagates unchanged
    }
    return { total: receipt.total, currency: receipt.currency };
  };
}
```

The port arrives through the constructor, never through Fastify's `decorate`. Building the plugin reaches no resource; registering it on an app and calling `listen` is the entrypoint's work. Mapping the decline to a 402 is handling: the router decides the outcome.

## A component that opens sessions

A realtime model holds a connection for the length of a conversation. The model opens sessions and stays stateless; the session holds the connection and closes it when it is disposed. The SDK's websocket connection has no test hook, so the edge component declares a view of the part it uses:

```ts
interface RealtimeConnection { // A view: the part of the SDK's connection the component uses
  send(event: Record<string, unknown>): void;
  on(type: "event", listener: (event: Record<string, unknown>) => void): void;
  close(): void;
}

type Connect = (options: { model: string }) => RealtimeConnection; // A view of opening the SDK's connection

interface RealtimeSession extends AsyncDisposable { // The session's interface: every method is valid until it is disposed
  send(event: ClientEvent): void;
  receive(): Promise<ServerEvent>;
}

interface RealtimeModel { // The component's interface: its lifecycle is part of it
  connect(): Promise<RealtimeSession>;
}

function newOpenAIRealtimeModel(openConnection: Connect, modelName: string): RealtimeModel { // An outbound edge component
  return { // reaches nothing
    async connect() {
      const connection = openConnection({ model: modelName }); // the resource, acquired when called
      return newOpenAIRealtimeSession(connection); // its [Symbol.asyncDispose] closes the connection
    },
  };
}
```

Its factory satisfies the view with the SDK's own connection, built only when a session opens:

```ts
import OpenAI from "openai";
import { OpenAIRealtimeWS } from "openai/realtime/ws";

function createOpenAIRealtimeModel(apiKey: string, modelName: string): RealtimeModel {
  const client = new OpenAI({ apiKey }); // reaches no resource
  return newOpenAIRealtimeModel((options) => new OpenAIRealtimeWS(options, client), modelName);
}
```

Whoever owns the conversation opens it: `await using session = await model.connect();`. The session is disposed, and the connection closed, when that block ends.

## Errors

The edge component handles what it can decide and lets everything else propagate:

```ts
function newStripePayments(fetch: SyncFetch, apiKey: string): StripePayments {
  return {
    charge(amount, currency) {
      const response = fetch(/* ... */); // a network error propagates unchanged
      if (response.status === 402) {
        return false; // handled: a decline is an answer the interface can give
      }
      return true;
    },
  };
}
```

Wrapping hides the error's origin:

```ts
    charge(amount, currency) {
      try {
        const response = fetch(/* ... */);
        /* ... */
      } catch (error) {
        throw new PaymentFailed("charge failed", { cause: error }); // bad: wraps an error the component did not determine
      }
    },
```
