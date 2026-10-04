# Dependency Injection in TypeScript

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is its TypeScript spelling. The vocabulary's TypeScript shapes — interfaces, function types, factory functions — live in [codebase-design's typescript.md](../codebase-design/typescript.md).

## Rule 1: code against interfaces

Type dependencies as `interface`s (for objects) or function types (for functions), never as a concrete's shape:

```ts
// Coupled: no seam — the caller is welded to one adapter
import { createStripeGateway } from "./stripe";

function processOrder(order: Order, gateway: ReturnType<typeof createStripeGateway>) { /* ... */ }

// Decoupled: PaymentGateway is the interface at the seam
// Any adapter — Stripe in production, a fake in tests — can satisfy it
function processOrder(order: Order, gateway: PaymentGateway) { /* ... */ }
```

`ReturnType<typeof createStripeGateway>` names one product: the type is welded to one factory's output. An `interface` declares what the caller needs — which is often a subset of any adapter's full surface.

## Rule 2: declare seams at construction

In this style, construction is a factory: the factory's signature is where the interface declares the seams; the returned object's methods take only data:

```ts
function createStripeGateway(apiKey: string, requester: (request: Request) => Response): PaymentGateway { // construction for the stripe gateway module includes the requester seam
  return {
    charge(amount: number) { /* ... */ }, // only data passed to the methods of the module, not seams
    refund(amount: number) { /* ... */ },
  };
}
```

A module-level singleton — `export const gateway = createStripeGateway(KEY, https)` imported by consumers — is the same dependency fetched instead of declared: TypeScript's ambient service locator. Reading `process.env` (or any resource) inside a body is the same fetch — present in behaviour, absent from the interface.

## Testing: the test wires the graph

A `beforeEach` (or plain setup) that assembles the graph with fakes is the test doing its own wiring — the same discipline at test scope. A fake is a small object literal satisfying the interface; a seam needs no mock library (`jest.fn()` verifies calls; it is not required to create one). Module mocking (`vi.mock`, `jest.mock`) is a service locator for tests: injecting a fake at the seam beats patching the module registry every time.

## Gotchas

- **`as` casts a fake past the checker.** `fake as PaymentGateway` asserts the shape without checking it — drift ships silently. Annotate (`const fake: PaymentGateway = { ... }`) or use `satisfies` so the literal is verified where it crosses the seam.
- **No framework needed.** `inversify`, `tsyringe`, and Nest-style decorators automate wiring; the discipline is types-only — typed parameters and factories carry it.
