# Codebase Design in TypeScript

The vocabulary in [SKILL.md](SKILL.md) is language-agnostic. This file is its TypeScript spelling.

The style throughout: **no classes**. Modules are functions and factory-built objects; adapters are object literals that satisfy an `interface` structurally.

## Vocabulary → TypeScript

| Term | TypeScript |
|---|---|
| **Interface** | for object shapes, an `interface`; for functions, a type — `() => Date` |
| **Adapter** | an object literal satisfying the interface's shape, built by a factory function |
| **Module** | a function, an object built by a factory function, or an ES module |
| **Seam** | a typed parameter behaviour varies through: an object interface, a function type, or a plain value |
| **Resource** | `process.env`, the filesystem, the clock, the network — reached only behind an adapter |

## Interfaces are types

```ts
interface PaymentGateway {            // the interface at the seam
  charge(amount: number): boolean;
}

function createStripeGateway(apiKey: string): PaymentGateway {
  return {
    charge(amount: number) { /* ... */ },  // checked against the interface here
  };
}
```

Matching is structural: the object satisfies the interface by shape alone, and the annotated return type checks the literal at the factory — drift is a compile error at the construction site. No `class`, no `implements`: `implements` buys the same check at the cost of constructor ceremony, `new` at call sites, and `this` binding.

- Prefer **`interface` for object shapes** and **`type` for unions and aliases**: a seam usually wants an `interface`; reach for a union when callers should discriminate between adapters.
- `satisfies` checks any expression against the interface without widening it.
- The type checker proves the shape, not the behaviour — it is no substitute for a test through the interface.

A function's interface is its type: `clock: () => Date` says everything a caller must know. When a function interface needs optional parameters, defaults, or a name, promote it to an interface with a call signature:

```ts
interface Clock {
  (tz?: string): Date;   // a call signature
}
```

## The shapes of a seam

A seam is anywhere behaviour varies without editing the module. In TypeScript it takes three shapes, declared in the factory's signature:

```ts
function createOrderProcessor(
  gateway: PaymentGateway,    // object interface: a whole adapter can cross it
  clock: () => Date,          // function interface: one function swaps
  verbose: boolean,           // plain value: one bit of behaviour
): OrderProcessor {
  /* ... */
}
```

All three are seams; they differ in **Depth**. An `interface` carries a whole interface of variation, a function type one function's worth, a `boolean` one bit. Fit the seam to the variation: an interface behind a binary toggle is ceremony; a boolean behind a swappable adapter is a wall.

## Modules don't need classes

A function with a typed parameter is already a module with a seam — no class, no framework, no decorators:

```ts
function processOrder(order: Order, gateway: PaymentGateway): Receipt { /* ... */ }
```

Adapters don't need classes either: the factory builds the object, a closure holds its state, and the literal satisfies the interface structurally:

```ts
function createStripeGateway(apiKey: string, requester: (request: Request) => Response): PaymentGateway {
  let retries = 0;                        // closure state — no instance, no `this`
  return {
    charge(amount: number) { /* ... */ }, // checked against PaymentGateway here
  };
}
```

This factory-plus-literal is the style: construction is an ordinary function call, state lives in closures, behaviour is data in an object rather than methods dispatched through `this`. Where a framework demands a `class` — decorators, `instanceof` — the factory still returns its instance behind the interface; callers never see a concrete.

## Adapters and seams

```ts
interface PaymentGateway { // PaymentGateway is an interface of the processOrder module seam
  charge(amount: number): boolean;
}

function processOrder(order: Order, paymentGateway: PaymentGateway) {
  /* ... */
}

function createStripeGateway(apiKey: string, requester: (request: Request) => Response): PaymentGateway { // a module — construction behind a function
  const gateway = {                    // the adapter's full surface
    charge(amount: number) { /* ... */ },
    refund(amount: number) { /* ... */ },
  };
  return gateway;                      // the interface needs only charge — a subset of the adapter's surface
}

processOrder(order, createStripeGateway(key, requester)); // the adapter crossing the processOrder module seam
```

## Designing for testability

**Accept dependencies, don't create them.**

```ts
// Testable
function processOrder(order: Order, paymentGateway: PaymentGateway) { // paymentGateway is a seam of the processOrder module
  /* ... */
}

// Hard to test
function processOrder(order: Order) {
  const gateway = createStripeGateway(KEY, http);
  /* ... */
}
```

**Return results, don't produce side effects.**

```ts
// Testable
function calculateDiscount(cart: Cart): Discount {
  /* ... */
}

// Hard to test
function applyDiscount(cart: Cart): void {
  cart.total -= discount;
  /* ... */
}
```

## Gotchas

- **Types are erased at runtime.** Interfaces are compile-time only; an `any` or an `as` cast slides a mis-shaped object across the seam unchecked. The seam holds only where the type checker can see it.
- **Fresh literals are excess-property checked** at returns, arguments, and `satisfies`. An adapter whose surface is wider than the interface (above) must pass through an intermediate `const` — the extra members are then structurally fine.
