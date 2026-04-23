# Funding Notes

Meridian's live rails do not just need credentials. They need funded wallets,
native gas, and enough runway to survive repeated simulations.

## Quick Checks

```bash
curl http://localhost:3010/funding
curl 'http://localhost:3010/funding?mode=cdp-base'
curl http://localhost:3010/health
curl http://localhost:4080/capabilities
cd services/atxp && pnpm run recover
```

Use `/funding` as the first source of truth for the ATXP service. It reports:

- payer mode
- destination network
- payer wallet address
- native gas balance
- USDC balance
- estimated transfers remaining
- recovery actions

You can pass `?mode=atxp|base|polygon|cdp-base` to inspect an alternate payer
mode without changing `.env`.

## ATXP Funding Paths

Official ATXP funding path:

```bash
npx atxp fund
npx atxp fund --amount 10
```

ATXP docs currently describe `fund` as returning:

- crypto deposit addresses for supported chains
- a shareable Stripe payment link for agent accounts

Useful when:

- `ATXP_PAYER_MODE=atxp`
- the hosted ATXP account path is the one you want to test

Useful docs:

- https://docs.atxp.ai/atxp/cli
- https://docs.atxp.ai/

## Onchain Payer Modes

### Polygon Amoy

If `ATXP_PAYER_MODE=polygon`, Meridian's direct-settle path depends on:

- Amoy USDC in the payer wallet
- Amoy POL for gas

USDC alone is not enough. If the wallet has no native gas runway, Meridian now
marks ATXP unavailable instead of advertising a false-green runtime.

Polygon's own docs now point Amoy funding to third-party faucets and note that
the old Polygon faucet is deprecated.

Useful docs:

- https://docs.polygon.technology/tools/gas/matic-faucet/
- https://polygon.technology/blog/introducing-the-amoy-testnet-for-polygon-pos

### Base Sepolia

If `ATXP_PAYER_MODE=base` or `cdp-base`, Base Sepolia is the most automation-
friendly test path because Coinbase CDP exposes a real faucet API.

For sustained local ATXP runtime, prefer:

```bash
ATXP_PAYER_MODE=cdp-base
ATXP_CDP_ACCOUNT_UNIQUE=false
```

That keeps ATXP on one shared CDP-funded payer account instead of creating a
fresh wallet per actor and hitting the faucet on every new identity.

Meridian already exposes a local wrapper:

```bash
curl -X POST http://localhost:3030/evm/request-faucet \
  -H 'content-type: application/json' \
  -d '{"address":"0x...","token":"eth"}'

curl -X POST http://localhost:3030/evm/request-faucet \
  -H 'content-type: application/json' \
  -d '{"address":"0x...","token":"usdc"}'
```

Official CDP docs currently state:

- Base Sepolia faucet support is available programmatically
- ETH, USDC, EURC, and cbBTC are supported assets
- ETH and USDC have claim limits per 24 hours

For `cdp-base`, Meridian now inspects the real shared payer account when
`ATXP_CDP_ACCOUNT_UNIQUE=false`, and otherwise inspects a probe wallet for that
mode in `/funding?mode=cdp-base`.

Useful docs:

- https://docs.cdp.coinbase.com/faucets/docs/welcome
- https://docs.cdp.coinbase.com/faucets/introduction/quickstart
- https://docs.cdp.coinbase.com/api-reference/v2/rest-api/faucets/request-funds-on-evm-test-networks

## Sustainable Test Strategy

For repeated local simulations, prefer funding paths in this order:

1. Base Sepolia plus CDP faucet automation for repeatable test replenishment.
2. ATXP account funding via `npx atxp fund` if the hosted ATXP path is the one
   under test.
3. Polygon Amoy only when you explicitly need Polygon behavior and have a
   reliable external POL faucet or another funded Amoy wallet.

## Current Dead Ends

As of April 22, 2026, live browser checks against `v1.kibble.sh` showed:

- `toChain=80002` -> `unsupported_chain`
- `toChain=84532` -> `unsupported_chain`

That means Kibble is not currently a solution for Meridian's Amoy or Base
Sepolia testnet treasury funding.
