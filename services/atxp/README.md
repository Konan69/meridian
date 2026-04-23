# Meridian ATXP

Direct ATXP integration service for Meridian using the official `@atxp/*` SDKs.

This service is intentionally Meridian-owned code. It does not depend on the
cloned SDK repo at runtime; it uses published packages from npm.

The current implementation uses `Hono` plus the ATXP server primitives and MCP
Web Standard transport.

Meridian's intended ATXP architecture is:

- one ATXP payee account for the server
- many payer accounts for agents, which may be:
  - `ATXPAccount` for the direct verify/settle runtime path
  - `BaseAccount` or `PolygonServerAccount` for official raw onchain payer experiments
  - CDP-backed Base payer as Meridian-owned experimental glue

## Env

Copy `.env.example` to `.env` and set:

- `ATXP_CONNECTION_STRING`
- optionally `ATXP_SERVER`
- `PORT`

## Run

```bash
npm install
npm run dev
```

## Probe Paid Tool Calls

Use the built-in payer factory to test different payer models against the local
ATXP MCP server:

```bash
npm run probe
```

For the direct verify/settle route that avoids the MCP payment-request loop:

```bash
npm run probe:direct
```

To diagnose payer-mode issues and print concrete recovery actions:

```bash
npm run recover
```

Set `ATXP_PAYER_MODE` in `.env` to one of:

- `atxp`
- `base`
- `polygon`
- `cdp-base`

For Meridian runtime readiness, prefer `atxp`.

`base` and `polygon` are official payer modes, but in Meridian they currently
produce raw onchain transaction credentials rather than the direct-settle
credential path the engine expects.

`cdp-base` is useful for experiments and for reusing Meridian's Coinbase Server
Wallet Base testnet wallets, but it is still Meridian-owned glue rather than an
official ATXP payer mode.

## Endpoints

- `GET /health`
- `POST /mcp`
- `POST /atxp/authorize`
- `POST /atxp/direct-transfer`

`/atxp/direct-transfer` is Meridian's supported ATXP verify/settle path. It
accepts an ATXP credential via `x-atxp-payment` and settles it directly through
ATXP's auth server without relying on the MCP payment-request completion loop.

`/atxp/authorize` creates a payer-side ATXP credential using the configured
payer mode. In production Meridian should only treat the service as
runtime-ready when `/health` reports `supportsDirectSettle=true`.

## Offline Protocol Contracts

The offline service tests document the ATXP helper contracts Meridian relies on
without live ATXP or CDP credentials. Keep this list aligned with `pnpm run
test:offline` and the helper files named here:

- `src/cdpTreasuryTopUp.test.ts` covers ATXP cdp-base treasury top-up amount boundary and default planning in `src/cdpTreasuryTopUp.ts`.
- `src/directTransfer.test.ts` covers ATXP direct-transfer raw transaction credential parsing in `src/directTransfer.ts`.
- `src/directTransfer.test.ts` covers ATXP direct-transfer own-field request shape and USDC amount boundary contracts in `src/directTransfer.ts`.
