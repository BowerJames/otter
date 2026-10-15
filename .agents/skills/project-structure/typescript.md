# Project Structure in TypeScript

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their TypeScript spelling.

## Vocabulary → TypeScript

| Term | TypeScript |
|---|---|
| **Package** | a directory with an `index.ts` |
| **Export file** | the package's `index.ts`, re-exporting names |
| **Data carrier** | an `interface` or `type` of plain, `readonly` data, or a union of literals |
| **Domain package** | `core/domain`, with one file per concept — `core/domain/currency.ts` |
| **Module factory package** | `infrastructure/factories/modules/<module-name>`, with the factories in `factory.ts` |
| **Adapter factory package** | `infrastructure/factories/adapters/<module-name>/<adapter-name>`, with the factories in `factory.ts` |
| **Entrypoint** | a function returned by a constructor in `infrastructure/entrypoints` — `newCli` in `infrastructure/entrypoints/cli.ts` |
| **Startup code** | a file beside the entrypoint that calls it — `infrastructure/entrypoints/cli.start.ts` |

**Package** here is a directory in one project, not an npm package. An ES module is a file; in these skills **module** keeps its codebase-design meaning, so this file says "file" for a `.ts` file.

Directories are kebab-case, so `<module_name>` in the rules is spelled `order-processor`.

## Example 1: a module and its adapters

An `OrderProcessor` module charges for an order through its `OrderProcessorPort`. A Stripe adapter and a PayPal adapter each satisfy that port.

```
src/
  core/
    domain/
      currency.ts              # Currency
    order-processor/
      index.ts                 # the export file
      interface.ts             # OrderProcessor
      port.ts                  # OrderProcessorPort
      data.ts                  # Order, OrderItem, Receipt
      errors.ts                # PaymentDeclined
      implementation.ts        # newOrderProcessor; could be several files
  infrastructure/
    adapters/
      order-processor/
        stripe/
          index.ts             # the export file
          adapter.ts           # newStripeAdapter
          http.ts              # Http, newRealHttp: the adapter's own port and what satisfies it
        paypal/
          index.ts             # the export file
          adapter.ts           # newPaypalAdapter
          http.ts              # Http, newRealHttp
    factories/
      modules/
        order-processor/
          index.ts             # the export file
          factory.ts           # createOrderProcessor
      adapters/
        order-processor/
          stripe/
            index.ts           # the export file
            factory.ts         # createStripeAdapter
          paypal/
            index.ts           # the export file
            factory.ts         # createPaypalAdapter
    entrypoints/
      cli.ts
      cli.start.ts
```

`Currency` means the same thing to every module and belongs to none, so it is in the domain package. `Order` and `Receipt` appear in the `OrderProcessor` interface, so they are in the module's data file:

```ts
// src/core/domain/currency.ts
export type Currency = "GBP" | "USD" | "EUR";
```

```ts
// src/core/order-processor/data.ts
import type { Currency } from "../domain/currency";

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
}
```

The interface, the port, the errors and the implementation each have their own file:

```ts
// src/core/order-processor/interface.ts
import type { Order, Receipt } from "./data";

export type OrderProcessor = (order: Order) => Receipt; // Interface for the module
```

```ts
// src/core/order-processor/port.ts
import type { Currency } from "../domain/currency";

export interface OrderProcessorPort { // The module's port
  charge(amount: number, currency: Currency): boolean;
}
```

```ts
// src/core/order-processor/errors.ts
export class PaymentDeclined extends Error {} // Determined by the module's implementation
```

```ts
// src/core/order-processor/implementation.ts
import type { Currency } from "../domain/currency";
import type { OrderProcessor } from "./interface";
import type { OrderProcessorPort } from "./port";

export function newOrderProcessor(
  port: OrderProcessorPort,
  currency: Currency,
): OrderProcessor { // Constructor for the module
  return function processOrder(order) { // Implementation of the module
    /* ... */
  };
}
```

```ts
// src/core/order-processor/index.ts
export type { Order, OrderItem, Receipt } from "./data";
export { PaymentDeclined } from "./errors";
export { newOrderProcessor } from "./implementation";
export type { OrderProcessor } from "./interface";
export type { OrderProcessorPort } from "./port";
```

An adapter imports the port from the module's export file:

```ts
// src/infrastructure/adapters/order-processor/stripe/adapter.ts
import type { OrderProcessorPort } from "../../../../core/order-processor";      // good: the export file
import type { OrderProcessorPort } from "../../../../core/order-processor/port"; // bad: reaches behind the export file
import { newPaypalAdapter } from "../paypal";                                    // bad: an adapter importing another adapter
import type { Http } from "./http";                                              // good: the adapter's own port, defined in its own package

export function newStripeAdapter(apiKey: string, http: Http): OrderProcessorPort { // Constructor for the stripe adapter
  return { // Adapter for the module's port
    charge(amount, currency) { /* ... */ },
  };
}
```

Nothing in `core` imports from `infrastructure`:

```ts
// src/core/order-processor/implementation.ts
import { newStripeAdapter } from "../../infrastructure/adapters/order-processor/stripe"; // bad: the core importing an adapter
```

## Example 2: the factory packages and an entrypoint

The adapter's export file exports what its adapter factory needs to build it: its constructor, its own port, and what satisfies that port in production:

```ts
// src/infrastructure/adapters/order-processor/stripe/index.ts
export { newStripeAdapter } from "./adapter";
export { newRealHttp } from "./http";
export type { Http } from "./http";
```

The adapter factory builds the adapter's parts and calls its constructor. It lives under `infrastructure/factories/adapters`, at the adapter's path:

```ts
// src/infrastructure/factories/adapters/order-processor/stripe/factory.ts
import type { OrderProcessorPort } from "../../../../../core/order-processor";
import { newRealHttp, newStripeAdapter } from "../../../../adapters/order-processor/stripe";

export function createStripeAdapter(apiKey: string): OrderProcessorPort { // An adapter factory: returns the port the adapter satisfies
  return newStripeAdapter(apiKey, newRealHttp());
}
```

```ts
// src/infrastructure/factories/adapters/order-processor/stripe/index.ts
export { createStripeAdapter } from "./factory";
```

The module factory chooses an adapter by calling its adapter factory, and never imports from an adapter's package:

```ts
// src/infrastructure/factories/modules/order-processor/factory.ts
import type { Currency } from "../../../../core/domain/currency";
import { newOrderProcessor } from "../../../../core/order-processor";
import type { OrderProcessor } from "../../../../core/order-processor";
import { createPaypalAdapter } from "../../adapters/order-processor/paypal";
import { createStripeAdapter } from "../../adapters/order-processor/stripe";
import { newStripeAdapter } from "../../../adapters/order-processor/stripe"; // bad: a module factory reaching into an adapter's package

export function createOrderProcessor(
  provider: "stripe" | "paypal",
  apiKey: string,
  currency: Currency,
): OrderProcessor { // A module factory for the order processor module
  switch (provider) {
    case "stripe":
      return newOrderProcessor(createStripeAdapter(apiKey), currency);
    case "paypal":
      return newOrderProcessor(createPaypalAdapter(apiKey), currency);
  }
}
```

```ts
// src/infrastructure/factories/modules/order-processor/index.ts
export { createOrderProcessor } from "./factory";
```

The entrypoint's constructor takes the entity it drives, and the entrypoint translates between the outside world and data carriers:

```ts
// src/infrastructure/entrypoints/cli.ts
import type { Order, OrderProcessor } from "../../core/order-processor";

export function newCli(
  orderProcessor: OrderProcessor, // Its constructor takes the interface it drives
): (argv: string[]) => void { // The entrypoint: calls no module's constructor and no factory, imports no adapter
  return function cli(argv) {
    const [id, ...costs] = argv;
    const order: Order = {
      id,
      items: costs.map((cost, i) => ({ name: `item_${i}`, cost: Number(cost) })),
    }; // translate the outside world into a data carrier
    const receipt = orderProcessor(order);
    console.log(`total=${receipt.total} ${receipt.currency}`);
  };
}
```

The startup code beside it reads the environment, calls the factory and passes the entity to the entrypoint's constructor:

```ts
// src/infrastructure/entrypoints/cli.start.ts
import { createOrderProcessor } from "../factories/modules/order-processor";
import { newCli } from "./cli";

const cli = newCli(createOrderProcessor("stripe", process.env.STRIPE_API_KEY!, "GBP"));
cli(process.argv.slice(2));
```

## Example 3: a module that needs another module

A `Checkout` module is built on top of order processing. It does not import `core/order-processor`. It declares its own data carriers and a port with the shape it needs:

```ts
// src/core/checkout/data.ts
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
// src/core/checkout/port.ts
import type { Cart } from "./data";

export interface CheckoutPort { // The checkout module's port
  pay(cart: Cart): number;
}
```

An adapter under `infrastructure/adapters/checkout` satisfies the port by calling an `OrderProcessor` through its interface, translating between the two modules' data carriers:

```ts
// src/infrastructure/adapters/checkout/order-processor/adapter.ts
import type { CheckoutPort } from "../../../../core/checkout";
import type { Order, OrderProcessor } from "../../../../core/order-processor";

export function newOrderProcessorAdapter(
  orderProcessor: OrderProcessor, // Constructor takes the interface, never the implementation
): CheckoutPort { // Adapter connecting checkout to the order processor module
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

The adapter's factory gets an `OrderProcessor` from the order processor's module factory package and passes it to the adapter's constructor:

```ts
// src/infrastructure/factories/adapters/checkout/order-processor/factory.ts
import type { CheckoutPort } from "../../../../../core/checkout";
import { newOrderProcessorAdapter } from "../../../../adapters/checkout/order-processor";
import { createOrderProcessor } from "../../../modules/order-processor";

export function createOrderProcessorAdapter(apiKey: string): CheckoutPort { // An adapter factory for the connecting adapter
  return newOrderProcessorAdapter(createOrderProcessor("stripe", apiKey, "GBP"));
}
```

The checkout module factory gets its adapter from that factory:

```ts
// src/infrastructure/factories/modules/checkout/factory.ts
import { newCheckout } from "../../../../core/checkout";
import type { Checkout } from "../../../../core/checkout";
import { createOrderProcessorAdapter } from "../../adapters/checkout/order-processor";

export function createCheckout(apiKey: string): Checkout { // A module factory for the checkout module
  return newCheckout(createOrderProcessorAdapter(apiKey));
}
```

## Example 4: the tests

```
tests/
  unit/
    core/
      order-processor/
        order-processor.test.ts    # constructs with newOrderProcessor and a fake adapter
        adapters.ts                # newFakeOrderProcessorAdapter: the test adapter for this module's port
      checkout/
        checkout.test.ts
        adapters.ts                # newFakeCheckoutAdapter
    infrastructure/
      adapters/
        order-processor/
          stripe/
            stripe.test.ts         # constructs with newStripeAdapter and a fake http
            adapters.ts            # newFakeHttp
        checkout/
          order-processor/
            order-processor.test.ts  # constructs with newOrderProcessorAdapter and a fake order processor
            adapters.ts              # newFakeOrderProcessor
      entrypoints/
        cli.test.ts                # constructs with newCli and a fake order processor
        adapters.ts                # newFakeOrderProcessor
  integration/
    infrastructure/
      adapters/
        order-processor/
          postgres/
            postgres.test.ts       # runs the postgres adapter against a real database
  e2e/
    cli.test.ts                    # where the project has end-to-end tests: runs the startup code
```

A test imports the entity under test from its export file and its test adapters from beside itself:

```ts
// tests/unit/core/order-processor/order-processor.test.ts
import { newOrderProcessor } from "../../../../src/core/order-processor";
import { newFakeOrderProcessorAdapter } from "./adapters";
```

The tests for `Checkout` do not import `newFakeOrderProcessorAdapter` or anything else from the order processor's tests. `Checkout` has its own port, so its tests have their own test adapter. The two `newFakeOrderProcessor` test adapters are duplicated for the same reason.

## Example 5: legacy code

A project has a legacy `billing.ts` that already talks to Stripe. A new `OrderProcessor` module reaches it through its port, with an adapter named for it:

```
src/
  billing.ts                     # legacy code, left where it is
  core/
    order-processor/
  infrastructure/
    adapters/
      order-processor/
        legacy-billing/
          index.ts
          adapter.ts             # newLegacyBillingAdapter: satisfies OrderProcessorPort by calling billing.ts
    factories/
      adapters/
        order-processor/
          legacy-billing/
            index.ts
            factory.ts           # createLegacyBillingAdapter
```

```ts
// src/infrastructure/adapters/order-processor/legacy-billing/adapter.ts
import { takePayment } from "../../../../billing";
import type { OrderProcessorPort } from "../../../../core/order-processor";

export function newLegacyBillingAdapter(): OrderProcessorPort {
  return {
    charge(amount, currency) {
      return takePayment(amount / 100, currency) === "ok";
    },
  };
}
```

Legacy code that needs an `OrderProcessor` calls the factory and drives the interface:

```ts
// src/views.ts, legacy code
import { createOrderProcessor } from "./infrastructure/factories/modules/order-processor"; // good: a module factory
import { newOrderProcessor } from "./core/order-processor";                                // bad: the constructor
```

## Checking the rules

ESLint's `no-restricted-imports` can enforce the export file by banning paths that reach past a package's `index.ts`. It can also keep constructors to the factories: constructors are named `new…`, so a pattern on `src/core` with `importNamePattern: "^new"` bans importing them, with an override switching the rule off for `src/infrastructure/factories/modules` and `tests`. The same pattern on `src/infrastructure/adapters`, switched off for `src/infrastructure/factories/adapters` and `tests`, keeps adapter constructors to their adapter factories. [dependency-cruiser](https://github.com/sverweij/dependency-cruiser) can enforce the import rules with `forbidden` rules: one stops `src/core` importing from `src/infrastructure`, one stops `src/core/domain` importing from any module's package, and one stops a module's package importing another module's package. A `forbidden` rule on npm dependencies can also stop `src/core` importing any third-party library.
