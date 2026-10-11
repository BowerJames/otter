# Factory Pattern in TypeScript

The rules in [SKILL.md](SKILL.md) are language-agnostic. This file is their TypeScript spelling. The vocabulary's TypeScript shapes — interfaces, function types, object literals — live in [codebase-design's typescript.md](../codebase-design/typescript.md).

## Example

Bad example for a `PaymentGateway` module:

```ts
interface PaymentGateway {
  charge(amount: number): boolean;
}

function createStripeGateway(apiKey: string, http: Http) {
  return {
    charge(amount: number): boolean { /* ... */ },
  };
}

function createPaypalGateway(apiKey: string, http: Http) {
  return {
    charge(amount: number): boolean { /* ... */ },
  };
}

function createPaymentGateway(
  type: "stripe" | "paypal",
  envVariableLoader: EnvVariableLoader,
  http: Http,
) { // This is not a factory for the PaymentGateway module: with no declared return type, the inferred type is the implementations' own shapes, not the module interface.
  switch (type) {
    case "stripe":
      return createStripeGateway(envVariableLoader("STRIPE_API_KEY"), http);
    case "paypal":
      return createPaypalGateway(envVariableLoader("PAYPAL_API_KEY"), http);
  }
}
```

Good example for a `PaymentGateway` module:

```ts
interface PaymentGateway {
  charge(amount: number): boolean;
}

function createStripeGateway(apiKey: string, http: Http): PaymentGateway {
  return {
    charge(amount) { /* ... */ },
  };
}

function createPaypalGateway(apiKey: string, http: Http): PaymentGateway {
  return {
    charge(amount) { /* ... */ },
  };
}

function createPaymentGateway(
  type: "stripe" | "paypal",
  envVariableLoader: EnvVariableLoader,
  http: Http,
): PaymentGateway { // This is now a factory for the PaymentGateway module since it declares the return type as the interface for the module.
  switch (type) {
    case "stripe":
      return createStripeGateway(envVariableLoader("STRIPE_API_KEY"), http);
    case "paypal":
      return createPaypalGateway(envVariableLoader("PAYPAL_API_KEY"), http);
  }
}
```
