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
