# Factory Pattern in TypeScript

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is its TypeScript spelling. The vocabulary's TypeScript shapes — interfaces, function types, factory functions — live in [codebase-design's typescript.md](../codebase-design/typescript.md).

## Rule 1: return the interface

```ts
function createPaymentGateway(config: Config, http: (request: Request) => Response): PaymentGateway {  // ingredients in the signature
  if (config.useStripe) {
    return createStripeGateway(config.stripeKey, http);   // the products are chosen here
  }
  return createPaypalGateway(config.paypalEnv, http);
}

// at a composition point — the ingredient concrete is named where concretes are named
const gateway = createPaymentGateway(config, createHttpRequests());  // caller never learns the product concrete
```

In this style each product has its own factory returning the interface — the object literal concrete appears only inside it. The switch above is the factory's *implementation*: the choice of concrete.

## Rule 2: bind runtime data to root-chosen adapters

Injected factories are function types — `(eid: EntityId) => EntityLoader`. Bind the root-time ingredient with an arrow closure: the one native form — no `functools.partial` equivalent needed:

```ts
const loaderFactory = (eid: EntityId) => createEntityLoader(eid, configSource);  // bound at the root

function createEntityEndpoints(loaderFactory: (eid: EntityId) => EntityLoader) { // the factory is the seam
  return {
    onGet(entityId: EntityId) {                          // data arrives at the boundary
      return createEntityService(loaderFactory(entityId)).handle();
    },
  };
}
```

A test injects an arrow fake and controls construction without touching globals:

```ts
const endpoints = createEntityEndpoints((eid) => createFakeLoader(eid));
```
