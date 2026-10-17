# Project Structure in TypeScript

The rules in [project-structure.md](../project-structure.md) are language-agnostic. This file is their TypeScript spelling.

## Vocabulary → TypeScript

| Term | TypeScript |
|---|---|
| **Package** | a directory with an `index.ts` |
| **Export file** | the package's `index.ts`, re-exporting names, with `export type` for the types |
| **Data carrier** | an `interface` or `type` of plain, `readonly` data, or a union of literals |
| **Contracts package** | `contracts`, with one file per concept — `contracts/currency.ts`, `contracts/agent-tool.ts` |
| **Contract** | an `interface` or a data carrier in its own file in `contracts` — `AgentTool` in `contracts/agent-tool.ts` |
| **Factory package** | `factories/components/<component-name>` or `factories/adapters/…`, with the factories in `factory.ts`, and a composite in a file named for it |
| **Entrypoint** | a file in `entrypoints` — `entrypoints/cli.ts` named in `package.json`'s `bin`, `entrypoints/server.ts` that Node runs to start Fastify |
| **Inbound edge component** | a component whose constructor returns a framework's object — `newOrdersRouter` returning a `FastifyPluginAsync` |
| **Outbound edge component** | a component whose constructor takes a library's object — `newStripePayments` taking sync-fetch's function |

The style throughout is **no classes**. A constructor is a function named `new…` (`newOrderProcessor`) that returns a function or an object literal satisfying the interface; a factory is named `create…` (`createOrderProcessor`). The one class is an error, a subclass of `Error`.

The examples put the project under `src/`, so every path below that does not start with `tests/` sits under `src`. Imports are relative.

**Package** here is a directory in one project, not an npm package. Node calls every file an ES module; this skill says "file" for a `.ts` file, and "component" for a package in `components`.

Directories and files are kebab-case, so `<component_name>` and `<port_name>` in the rules are spelled `order-processor` and `place-order`; in its constructor the port is named `placeOrder`.

Files behind the export file `export` what their siblings need. The export file decides what is public: a name is public if `index.ts` re-exports it, and private to the package otherwise.

## Example 1: a component and its ports

An `OrderProcessor` component charges for an order through its `payments` port, and stamps the receipt through its `clock` port.

```
src/
  contracts/
    currency.ts                # Currency
  components/
    order-processor/
      index.ts                 # the export file
      interface.ts             # OrderProcessor
      ports.ts                 # Payments, Clock
      data.ts                  # Order, OrderItem, Receipt
      errors.ts                # PaymentDeclined
      implementation.ts        # newOrderProcessor; could be several files
```

`Currency` was promoted to the contracts package when a second component needed it and it meant the same thing to both. `Order` and `Receipt` appear in the `OrderProcessor` interface, so they are in the component's data file:

```ts
// src/contracts/currency.ts
export type Currency = "GBP" | "USD" | "EUR";
```

```ts
// src/components/order-processor/data.ts
import type { Currency } from "../../contracts/currency";

export interface OrderItem {
  readonly name: string;
  readonly cost: number; // in the currency's minor unit
}

export interface Order {
  readonly id: string;
  readonly items: readonly OrderItem[];
}

export interface Receipt {
  readonly total: number;
  readonly currency: Currency;
  readonly at: number; // milliseconds since the epoch
}
```

The interface, the ports, the errors and the implementation each have their own file:

```ts
// src/components/order-processor/interface.ts
import type { Order, Receipt } from "./data";

export type OrderProcessor = (order: Order) => Receipt; // Interface for the component
```

```ts
// src/components/order-processor/ports.ts
import type { Currency } from "../../contracts/currency";

export interface Payments { // The interface of the payments port
  charge(amount: number, currency: Currency): boolean;
}

export type Clock = () => number; // The interface of the clock port: milliseconds since the epoch
```

```ts
// src/components/order-processor/errors.ts
export class PaymentDeclined extends Error {} // Determined by the component's implementation
```

```ts
// src/components/order-processor/implementation.ts
import type { Currency } from "../../contracts/currency";
import { PaymentDeclined } from "./errors";
import type { OrderProcessor } from "./interface";
import type { Clock, Payments } from "./ports";

export function newOrderProcessor(
  payments: Payments,
  clock: Clock,
  currency: Currency,
): OrderProcessor { // Constructor for the component
  return function processOrder(order) { // Implementation of the component
    /* ... */
  };
}
```

```ts
// src/components/order-processor/index.ts
export type { Order, OrderItem, Receipt } from "./data";
export { PaymentDeclined } from "./errors";
export { newOrderProcessor } from "./implementation";
export type { OrderProcessor } from "./interface";
export type { Clock, Payments } from "./ports";
```

A component imports nothing from another component, an adapter or a factory:

```ts
// src/components/order-processor/implementation.ts
import { newStripePayments } from "../stripe-payments";                              // bad: a component importing another component
import { createStripePayments } from "../../factories/components/stripe-payments";   // bad: a component importing a factory
```

## Example 2: an outbound edge component and its factory

`StripePayments` faces Stripe's HTTP API. It is the only package in the project that knows Stripe's request format:

```
src/
  components/
    stripe-payments/
      index.ts                 # the export file
      interface.ts             # StripePayments
      views.ts                 # SyncFetch: its view of the sync-fetch library's function
      implementation.ts        # newStripePayments: the humble shell, taking a SyncFetch
      translate.ts             # toChargeForm, charged: plain functions
  factories/
    components/
      order-processor/
        index.ts
        factory.ts             # createOrderProcessor
      stripe-payments/
        index.ts
        factory.ts             # createStripePayments
```

sync-fetch offers no test hook of its own, so the component declares a view: the part of the library's function it calls. The library's function satisfies it by shape, and the tests pass a fake of it:

```ts
// src/components/stripe-payments/views.ts
export type SyncFetch = ( // A view: what this component uses of sync-fetch
  url: string,
  init: { method: "POST"; headers: Record<string, string>; body: string },
) => { readonly status: number };
```

```ts
// src/components/stripe-payments/implementation.ts
import type { Currency } from "../../contracts/currency";
import type { StripePayments } from "./interface";
import { charged, toChargeForm } from "./translate";
import type { SyncFetch } from "./views";

export function newStripePayments(fetch: SyncFetch, apiKey: string): StripePayments { // An outbound edge component; its constructor takes the library's function
  return {
    charge(amount: number, currency: Currency) { // the humble shell
      const response = fetch("https://api.stripe.com/v1/charges", {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/x-www-form-urlencoded" },
        body: toChargeForm(amount, currency),
      });
      return charged(response.status);
    },
  };
}
```

Its export file exports the view with the interface and the constructor, which is what its factory and its tests need:

```ts
// src/components/stripe-payments/index.ts
export { newStripePayments } from "./implementation";
export type { StripePayments } from "./interface";
export type { SyncFetch } from "./views";
```

Its factory passes the library's function, and returns the interface:

```ts
// src/factories/components/stripe-payments/factory.ts
import syncFetch from "sync-fetch";
import { newStripePayments } from "../../../components/stripe-payments";
import type { StripePayments } from "../../../components/stripe-payments";

export function createStripePayments(apiKey: string): StripePayments {
  return newStripePayments(syncFetch, apiKey); // Passing the function reaches no resource
}
```

`StripePayments` satisfies the order processor's `payments` port as it is, so the order processor's factory passes it straight to the port. There is no adapter:

```ts
// src/factories/components/order-processor/factory.ts
import { newOrderProcessor } from "../../../components/order-processor";
import type { OrderProcessor } from "../../../components/order-processor";
import type { Currency } from "../../../contracts/currency";
import { createStripePayments } from "../stripe-payments";

export function createOrderProcessor(apiKey: string, currency: Currency): OrderProcessor {
  return newOrderProcessor(createStripePayments(apiKey), Date.now, currency);
}
```

## Example 3: an adapter joining two components

A `Checkout` component is built on top of order processing. It does not import `components/order-processor`. It declares its own data carriers and a `payment` port with the shape it needs:

```ts
// src/components/checkout/data.ts
export interface CartLine {
  readonly product: string;
  readonly price: number;
}

export interface Cart {
  readonly id: string;
  readonly lines: readonly CartLine[];
}
```

```ts
// src/components/checkout/ports.ts
import type { Cart } from "./data";

export interface Payment { // The interface of checkout's payment port
  pay(cart: Cart): number;
}
```

The order processor's interface does not satisfy that port as it is, so an adapter under `adapters/checkout/payment` satisfies it by calling the order processor, translating between the two components' data carriers:

```ts
// src/adapters/checkout/payment/order-processor/adapter.ts
import type { Payment } from "../../../../components/checkout";
import type { Order, OrderProcessor } from "../../../../components/order-processor";

export function newOrderProcessorAdapter(
  orderProcessor: OrderProcessor, // Takes the interface of the component it calls
): Payment { // Adapter joining checkout to the order processor
  return {
    pay(cart) {
      const order: Order = {
        id: cart.id,
        items: cart.lines.map((line) => ({ name: line.product, cost: line.price })),
      }; // checkout's data, translated into the order processor's
      return orderProcessor(order).total;
    },
  };
}
```

```ts
// src/adapters/checkout/payment/order-processor/index.ts
export { newOrderProcessorAdapter } from "./adapter";
```

Its factory lives at the same path under `factories/adapters`, and the checkout's factory uses it:

```ts
// src/factories/adapters/checkout/payment/order-processor/factory.ts
import { newOrderProcessorAdapter } from "../../../../../adapters/checkout/payment/order-processor";
import type { Payment } from "../../../../../components/checkout";
import type { OrderProcessor } from "../../../../../components/order-processor";

export function createOrderProcessorPayment(orderProcessor: OrderProcessor): Payment { // Returns the port's interface
  return newOrderProcessorAdapter(orderProcessor);
}
```

```ts
// src/factories/components/checkout/factory.ts
import { newCheckout } from "../../../components/checkout";
import type { Checkout } from "../../../components/checkout";
import { createOrderProcessorPayment } from "../../adapters/checkout/payment/order-processor";
import { createOrderProcessor } from "../order-processor";

export function createCheckout(apiKey: string): Checkout {
  return newCheckout(createOrderProcessorPayment(createOrderProcessor(apiKey, "GBP")));
}
```

An adapter imports only from the export files of the components it joins:

```ts
// src/adapters/checkout/payment/order-processor/adapter.ts
import type { OrderProcessor } from "../../../../components/order-processor/interface"; // bad: reaches behind the export file
import { newOrderProcessor } from "../../../../components/order-processor";             // bad: an adapter importing a constructor
import { newRetryingPayment } from "../retrying";                                       // bad: an adapter importing another adapter
import syncFetch from "sync-fetch";                                                     // bad: reaching a resource is an edge component's work
```

## Example 4: inbound edge components and their entrypoints

The program is started two ways: from the command line, and as a web server. Each way has an inbound edge component that its framework calls, and an entrypoint that starts it:

```
src/
  components/
    orders-cli/
      index.ts
      ports.ts                 # PlaceOrder
      data.ts                  # NewOrder, Placed
      implementation.ts        # newOrdersCli: returns a Commander Command
    orders-router/
      index.ts
      ports.ts                 # PlaceOrder
      data.ts                  # NewOrder, Placed
      bodies.ts                # orderBody, receiptBody: the routes' JSON Schemas, part of the foreign interface
      implementation.ts        # newOrdersRouter: returns a FastifyPluginAsync
  adapters/
    orders-cli/
      place-order/
        order-processor/       # newOrderProcessorAdapter
    orders-router/
      place-order/
        order-processor/       # newOrderProcessorAdapter
  entrypoints/
    cli.ts
    server.ts
```

Neither has an interface file: its interface is the framework's. Its port is the project's own:

```ts
// src/components/orders-cli/implementation.ts
import { Command } from "commander";
import type { PlaceOrder } from "./ports";

export function newOrdersCli(placeOrder: PlaceOrder): Command { // Constructor: returns the shape Commander runs
  const place = new Command("place")
    .argument("<order-id>")
    .argument("<costs...>")
    .action((orderId: string, costs: string[]) => { // the humble shell
      const placed = placeOrder({ id: orderId, costs: costs.map(Number) });
      if (placed === undefined) {
        place.error("payment declined"); // handled: a failed exit is the answer
      }
      console.log(`total=${placed.total} ${placed.currency}`);
    });
  return place;
}
```

The two components each declare `PlaceOrder` and their own data carriers. They have the same shape, so promoting them to the contracts package is worth considering, but only if they mean the same thing to both. Until then, each has its own adapter to the order processor.

Each entrypoint reads the environment, builds the assembly through factories, registers the inbound edge component with its framework, and starts it:

```ts
#!/usr/bin/env node
// src/entrypoints/cli.ts
import { createOrdersCli } from "../factories/components/orders-cli";

// package.json: "bin": { "shop": "dist/entrypoints/cli.js" }
const cli = createOrdersCli(process.env.STRIPE_API_KEY!, "GBP");
cli.parse(); // starts Commander
```

```ts
// src/entrypoints/server.ts
import Fastify from "fastify";
import { createOrdersRouter } from "../factories/components/orders-router";

const app = Fastify(); // node dist/entrypoints/server.js
app.register(createOrdersRouter(process.env.STRIPE_API_KEY!, "GBP"));
await app.listen({ port: 3000 });
```

The factory of an inbound edge component returns its foreign interface:

```ts
// src/factories/components/orders-router/factory.ts
import type { FastifyPluginAsync } from "fastify";
import { newOrdersRouter } from "../../../components/orders-router";
import type { Currency } from "../../../contracts/currency";
import { createOrderProcessorPlaceOrder } from "../../adapters/orders-router/place-order/order-processor";
import { createOrderProcessor } from "../order-processor";

export function createOrdersRouter(apiKey: string, currency: Currency): FastifyPluginAsync {
  return newOrdersRouter(createOrderProcessorPlaceOrder(createOrderProcessor(apiKey, currency)));
}
```

When what an inbound edge component calls holds one request's resources, its port is an opener: a function that returns the interface. A `PhoneCall` component talks to a caller for the length of a call, over a line the router presents in the project's own shape. The `WebSocket` belongs to Fastify's foreign interface, so it never leaves the router:

```ts
// src/components/call-router/ports.ts
import type { CallDetails } from "./data";

export interface Line { // The project's shape for a caller's connection
  say(audio: Uint8Array): Promise<void>;
  hear(): Promise<Uint8Array>;
}

export interface Call {
  run(): Promise<void>;
}

export type OpenCall = (line: Line, details: CallDetails) => Call; // The port: opens a call per request
```

```ts
// src/components/call-router/implementation.ts
import type { FastifyPluginAsync } from "fastify";
import { on } from "node:events";
import type { WebSocket } from "ws";
import type { Line, OpenCall } from "./ports";

export function newCallRouter(path: string, openCall: OpenCall): FastifyPluginAsync {
  return async (app) => {
    app.get<{ Querystring: { ddiNo: string } }>(path, { websocket: true }, async (socket, request) => { // the humble shell
      await openCall(webSocketLine(socket), { ddiNumber: request.query.ddiNo }).run();
    });
  };
}

function webSocketLine(socket: WebSocket): Line { // presents the foreign socket as the project's Line
  const messages = on(socket, "message"); // buffers what arrives between hears
  return {
    async say(audio) {
      socket.send(audio);
    },
    async hear() {
      const { value: [data] } = await messages.next();
      return new Uint8Array(data);
    },
  };
}
```

The router's factory satisfies the opener with a factory of the phone call component:

```ts
// src/factories/components/call-router/factory.ts
export function createCallRouter(model: RealtimeModel): FastifyPluginAsync {
  return newCallRouter("/call", (line, details) => createPhoneCall(model, line, details));
}
```

Fastify reaches the router only once the entrypoint has registered the websocket plugin with it, which is registering and starting a foreign component:

```ts
// src/entrypoints/server.ts
app.register(fastifyWebsocket);
app.register(createCallRouter(createRealtimeModel(process.env.OPENAI_API_KEY!)));
```

## Example 5: a contract and its adapters

A `ToolRunner` component runs the tools a model calls. A tool means the same thing to every entity that uses it, so `AgentTool` is a contract. The tool runner's `tools` port takes an array of them:

```
src/
  contracts/
    agent-tool.ts              # AgentTool: a contract
  components/
    tool-runner/
      implementation.ts        # newToolRunner(tools: readonly AgentTool[])
  adapters/
    agent-tool/                # the adapters of the AgentTool contract
      order-processor/
        adapter.ts             # newPlaceOrderTool: places an order through the OrderProcessor component
      truncated/
        adapter.ts             # newTruncatedTool: a decorator, shortening what a tool returns
  factories/
    adapters/
      agent-tool/
        order-processor/       # createPlaceOrderTool
        truncated/             # createTruncatedTool
    components/
      tool-runner/             # createToolRunner
```

The contract has a shape and no behaviour:

```ts
// src/contracts/agent-tool.ts
export interface AgentTool { // A contract: the same meaning to every entity that uses it
  readonly name: string;
  readonly description: string;
  readonly parameters: Readonly<Record<string, unknown>>; // the JSON Schema of execute's arguments
  execute(args: Record<string, unknown>): Promise<string>;
}
```

```ts
// src/components/tool-runner/implementation.ts
import type { AgentTool } from "../../contracts/agent-tool";
import type { ToolRunner } from "./interface";

export function newToolRunner(tools: readonly AgentTool[]): ToolRunner { // A port typed by a contract, taking several implementations
  const byName = new Map(tools.map((tool) => [tool.name, tool]));
  /* ... */
}
```

Each tool is an adapter of the contract, under `adapters/agent-tool`. One joins the order processor component, so it is named for it:

```ts
// src/adapters/agent-tool/order-processor/adapter.ts
import type { OrderProcessor } from "../../../components/order-processor";
import type { AgentTool } from "../../../contracts/agent-tool";

export function newPlaceOrderTool(
  orderProcessor: OrderProcessor, // Takes the component's interface, never its implementation
): AgentTool { // An adapter of the contract, joining the order processor component
  return {
    name: "place_order",
    description: "Place the caller's order.",
    parameters: { type: "object", properties: { id: { type: "string" }, costs: { type: "array" } } },
    async execute(args) {
      const costs = args.costs as number[];
      const receipt = orderProcessor({
        id: args.id as string,
        items: costs.map((cost, i) => ({ name: `item_${i}`, cost })),
      });
      return `Charged ${receipt.total} ${receipt.currency}.`;
    },
  };
}
```

A decorator of the contract is reused by wrapping, never by importing:

```ts
// src/adapters/agent-tool/truncated/adapter.ts
import type { AgentTool } from "../../../contracts/agent-tool";

export function newTruncatedTool(
  inner: AgentTool, // Takes the interface it satisfies
  maxChars: number,
): AgentTool { // A decorator of the contract
  return {
    name: inner.name,
    description: inner.description,
    parameters: inner.parameters,
    async execute(args) {
      return (await inner.execute(args)).slice(0, maxChars);
    },
  };
}
```

The factories combine them:

```ts
// src/factories/adapters/agent-tool/order-processor/factory.ts
import { newPlaceOrderTool } from "../../../../adapters/agent-tool/order-processor";
import type { OrderProcessor } from "../../../../components/order-processor";
import type { AgentTool } from "../../../../contracts/agent-tool";
import { createTruncatedTool } from "../truncated";

export function createPlaceOrderTool(orderProcessor: OrderProcessor): AgentTool { // Returns the contract it satisfies
  return createTruncatedTool(newPlaceOrderTool(orderProcessor), 2_000);
}
```

```ts
// src/factories/components/tool-runner/factory.ts
import type { OrderProcessor } from "../../../components/order-processor";
import { newToolRunner } from "../../../components/tool-runner";
import type { ToolRunner } from "../../../components/tool-runner";
import { createPlaceOrderTool } from "../../adapters/agent-tool/order-processor";

export function createToolRunner(orderProcessor: OrderProcessor): ToolRunner {
  return newToolRunner([createPlaceOrderTool(orderProcessor)]);
}
```

## Example 6: the tests

```
tests/
  unit/
    components/
      order-processor/
        order-processor.test.ts    # constructs with newOrderProcessor, newFakePayments and a fixed clock
        fakes.ts                   # newFakePayments: the fake for this component's payments port
      checkout/
        checkout.test.ts
        fakes.ts                   # newFakePayment
      stripe-payments/
        stripe-payments.test.ts    # constructs with newStripePayments and a fake of its SyncFetch view
        fakes.ts                   # newFakeSyncFetch
      orders-router/
        orders-router.test.ts      # drives newOrdersRouter through Fastify's app.inject
        fakes.ts                   # newFakePlaceOrder
    adapters/
      checkout/
        payment/
          order-processor/
            order-processor.test.ts  # constructs with newOrderProcessorAdapter and newFakeOrderProcessor
            fakes.ts                 # newFakeOrderProcessor
      agent-tool/
        truncated/
          truncated.test.ts        # constructs with newTruncatedTool and newFakeAgentTool
          fakes.ts
  integration/
    components/
      postgres-orders/
        postgres-orders.test.ts    # runs newPostgresOrders against a real database
  e2e/
    cli.test.ts                    # where the project has end-to-end tests: runs entrypoints/cli.ts
```

A test imports the entity under test from its export file and its fakes from beside itself:

```ts
// tests/unit/components/order-processor/order-processor.test.ts
import { newOrderProcessor, type OrderProcessor } from "../../../../src/components/order-processor";
import { newFakePayments } from "./fakes";
```

The tests for `Checkout` do not import `newFakePayments` or anything else from the order processor's tests. `Checkout` has its own ports, so its tests have their own fakes. The two `newFakeOrderProcessor` fakes are duplicated for the same reason.

## Example 7: legacy code

A project has a legacy `billing.ts` that already talks to Stripe. A new `OrderProcessor` component reaches it through its `payments` port, satisfied by an outbound edge component that faces the legacy code:

```
src/
  billing.ts                     # legacy code, left where it is
  components/
    order-processor/
    legacy-billing/
      index.ts
      interface.ts               # LegacyBilling
      implementation.ts          # newLegacyBilling: calls billing.ts
  factories/
    components/
      legacy-billing/
        index.ts
        factory.ts               # createLegacyBilling
```

```ts
// src/components/legacy-billing/implementation.ts
import { takePayment } from "../../billing";                 // good: the legacy code this edge component faces
import type { LegacyBilling } from "./interface";

export function newLegacyBilling(): LegacyBilling {
  return {
    charge(amount, currency) {
      return takePayment(amount / 100, currency) === "ok";
    },
  };
}
```

Legacy code that needs an `OrderProcessor` calls its factory and uses its interface:

```ts
// src/views.ts, legacy code
import { createOrderProcessor } from "./factories/components/order-processor"; // good: a factory
import { newOrderProcessor } from "./components/order-processor";              // bad: the constructor
```

A task that changes how `billing.ts` rounds amounts changes it in place. A task that rewrites how payments are taken may move that behaviour into a `stripe-payments` component, leaving `billing.ts` calling its factory, as far as the change needs and no further.

## Checking the rules

[dependency-cruiser](https://github.com/sverweij/dependency-cruiser) can enforce the import rules with `forbidden` rules:

```js
// .dependency-cruiser.cjs
module.exports = {
  options: {
    tsPreCompilationDeps: true, // an `import type` counts as an import
    doNotFollow: { path: "node_modules" },
  },
  forbidden: [
    {
      name: "nothing-imports-an-entrypoint",
      severity: "error",
      from: {},
      to: { path: "^src/entrypoints/" },
    },
    {
      name: "only-factories-and-entrypoints-import-factories",
      severity: "error",
      from: { path: "^src/(adapters|components|contracts)/" },
      to: { path: "^src/factories/" },
    },
    {
      name: "components-and-contracts-never-import-adapters",
      severity: "error",
      from: { path: "^src/(components|contracts)/" },
      to: { path: "^src/adapters/" },
    },
    {
      name: "components-never-import-each-other",
      severity: "error",
      from: { path: "^src/components/([^/]+)/" },
      to: { path: "^src/components/", pathNot: "^src/components/$1/" },
    },
    {
      name: "contracts-import-nothing-from-outside",
      severity: "error",
      from: { path: "^src/contracts/" },
      to: { pathNot: "^src/contracts/" },
    },
    {
      name: "adapters-import-no-library",
      severity: "error",
      from: { path: "^src/adapters/" },
      to: { dependencyTypes: ["npm", "npm-dev", "npm-optional", "npm-peer"] },
    },
    {
      name: "only-the-edge-component-facing-stripe-uses-sync-fetch",
      severity: "error",
      from: { path: "^src/", pathNot: "^src/(components|factories/components)/stripe-payments/" },
      to: { path: "^node_modules/sync-fetch/" },
    },
  ],
};
```

The first three rules and the contracts rule put the layers in order — entrypoints, factories, adapters, components, contracts — with each importing only from the layers after it; the fourth keeps the components independent of each other.

dependency-cruiser works on files, not names, so it cannot tell an import of `newOrderProcessor` from an import of `OrderProcessor`. ESLint's `no-restricted-imports` can: constructors are named `new…`, so a pattern with `importNamePattern: "^new"` bans importing them from a component or an adapter, and the same rule bans reaching past a component's `index.ts`. A second config block for `src/factories` and `tests` keeps the export-file pattern and drops the constructor one:

```js
// eslint.config.js
const pastTheExportFile = {
  group: ["**/components/*/*"],
  message: "Import a component from its index.ts.",
};
const constructors = {
  group: ["**/components/*", "**/adapters/**"],
  importNamePattern: "^new",
  message: "Constructors are imported only by factories and tests.",
};

export default [
  {
    files: ["src/**/*.ts"],
    rules: { "no-restricted-imports": ["error", { patterns: [pastTheExportFile, constructors] }] },
  },
  {
    files: ["src/factories/**/*.ts", "tests/**/*.ts"],
    rules: { "no-restricted-imports": ["error", { patterns: [pastTheExportFile] }] },
  },
];
```
