# Finance-God Injective Bridge Rules

## Isolation

- This repository is an independent Testnet-only service.
- Never modify, mount, import from, or connect directly to the Finance-God
  repository or database.
- Finance-God access is opt-in, on-demand, and HTTP GET-only. Never call login,
  desk bootstrap, or any mutating Finance-God endpoint.
- Do not join Finance-God Docker networks or reuse its ports, volumes, secrets,
  environment files, or database.

## Execution safety

- Refuse every network other than Injective Testnet.
- Keep the signing key in process memory only. Never log, persist, serialize, or
  return it.
- AI or source snapshots never authorize an order. Only a reviewed, unexpired
  `InjectivePlan` explicitly confirmed through the Bridge API may reach signing.
- A transaction hash is not an accepted order. Reconcile transaction and order
  state before reporting success or retrying an unknown broadcast.
- Use `Decimal` for every price, quantity, balance, and notional.
- Surface failures explicitly; never replace failed RPC, indexer, or Finance-God
  reads with fabricated data.

## Validation

- Run unit and integration tests, Ruff, and the isolation verifier.
- Live Testnet smoke tests must remain opt-in and require a dedicated funded
  wallet.
