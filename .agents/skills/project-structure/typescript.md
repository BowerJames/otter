# Project Structure in TypeScript

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their TypeScript spelling.

## Vocabulary → TypeScript

| Term | TypeScript |
|---|---|
| **Package** | a directory with an `index.ts` |
| **Entry point** | the package's `index.ts`, re-exporting names |
| **Data carrier** | an `interface` or `type` of plain data |
| **Domain package** | a `domain` directory with one file per concept — `domain/order.ts` |

**Package** here is a directory in one project, not an npm package. An ES module is a file; in these skills **module** keeps its codebase-design meaning, so this file says "file" for a `.ts` file.

## Example 1: first use

`Order` is first needed by the `OrderProcessor` module, so it is defined in that module's package.

```
src/
  order-processor/
    index.ts               # the entry point
    order-processor.ts     # OrderProcessor, createOrderProcessor
    types.ts               # Order, OrderItem, Receipt
  payment-gateway/
    index.ts               # the entry point
    payment-gateway.ts     # PaymentGateway, createPaymentGateway
    stripe.ts              # createStripeGateway
    paypal.ts              # createPaypalGateway
```

```ts
// order-processor/index.ts
export { createOrderProcessor } from "./order-processor";
export type { OrderProcessor } from "./order-processor";
export type { Order, OrderItem, Receipt } from "./types";
```

```ts
// payment-gateway/index.ts
export { createPaymentGateway } from "./payment-gateway"; // createStripeGateway and createPaypalGateway are not exported
export type { PaymentGateway } from "./payment-gateway";
```

`Order` and `Receipt` appear in the `OrderProcessor` interface, so the entry point exports them. Another package imports only from an entry point:

```ts
// order-processor/order-processor.ts
import type { PaymentGateway } from "../payment-gateway";       // good: the entry point
import { createStripeGateway } from "../payment-gateway/stripe"; // bad: reaches behind the entry point
```

## Example 2: second use

Three new modules each need `Order`. Each one meets a different question from rule 2.

**Only a slice.** An `AuditLog` module records which orders were processed. It reads only the id, so it declares its own interface and imports nothing:

```ts
// audit-log/audit-log.ts
interface Identified { // the slice of Order this module needs
  id: string;
}
```

`Order` satisfies `Identified` by shape, so an `Order` can be passed without `audit-log` knowing the type exists.

**Already depends on the owner.** A `Checkout` module is built on top of an `OrderProcessor`, so it already imports that module's interface. It imports `Order` from the same entry point:

```ts
// checkout/checkout.ts
import type { Order, OrderProcessor, Receipt } from "../order-processor";
```

**Otherwise.** An `Invoicing` module needs the whole `Order` and has nothing to do with order processing. `Order` now has no single owner, so it moves to the domain package:

```
src/
  domain/
    order.ts               # Order, OrderItem
  invoicing/
    index.ts
    invoicing.ts           # import type { Order } from "../domain/order"
  order-processor/
    index.ts
    order-processor.ts     # import type { Order } from "../domain/order"
    types.ts               # Receipt stays: only this module's interface uses it
```

The entry point can keep re-exporting `Order` while callers are updated, so the move is one definition and its import lines:

```ts
// order-processor/index.ts
export type { Order, OrderItem } from "../domain/order"; // re-exported until callers import from domain/order
export { createOrderProcessor } from "./order-processor";
export type { OrderProcessor } from "./order-processor";
export type { Receipt } from "./types";
```

Tests that drive `OrderProcessor` through its factory and interface do not change.

## Checking the rules

ESLint's `no-restricted-imports` can enforce rule 1 by banning paths that reach past a package's `index.ts`, and [dependency-cruiser](https://github.com/sverweij/dependency-cruiser) can enforce rule 3: a `forbidden` rule stops `domain` importing from any module's package, and its `circular` check catches cycles.
