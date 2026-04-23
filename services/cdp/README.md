# Meridian CDP Server Wallet

Direct Coinbase Server Wallet v2 integration service for Meridian.

Uses the official `@coinbase/cdp-sdk` package for:

- creating or reusing EVM accounts
- requesting faucet funds on Base Sepolia
- signing EIP-712 typed data
- signing messages

## Env

- `CDP_API_KEY_ID`
- `CDP_API_KEY_SECRET`
- `CDP_WALLET_SECRET`
- `PORT`

These must be `Server Wallet` credentials. Embedded Wallet credentials are not
compatible with Meridian's backend-owned x402 flow.

## Run

```bash
npm install
npm run dev
```

## Offline Protocol Contracts

The offline service tests document the protocol helper contracts Meridian relies
on without live CDP credentials. Keep this list aligned with `pnpm run
test:offline` and the helper files named here:

- `services/cdp/src/signMessage.test.ts` covers CDP sign-message exact byte preservation and own-field validation in `services/cdp/src/signMessage.ts`, with shared request validation in `services/cdp/src/requestValidation.ts`.
- `services/cdp/src/sendTransaction.test.ts` covers CDP send-transaction network/value normalization and own-field validation in `services/cdp/src/sendTransaction.ts`, with shared request validation in `services/cdp/src/requestValidation.ts`.
- `services/cdp/src/signTypedData.test.ts` covers CDP sign-typed-data exact key, primaryType, nested own-key, and message own-field semantics in `services/cdp/src/signTypedData.ts`, with shared request validation in `services/cdp/src/requestValidation.ts`.
- `services/cdp/src/treasury.test.ts` covers CDP treasury native and USDC transfer route request/response contracts in `services/cdp/src/treasury.ts`.
