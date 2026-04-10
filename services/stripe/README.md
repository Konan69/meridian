# Meridian Stripe

Direct Stripe-backed integration service for Meridian.

This service is the landing zone for:

- `MPP` machine payments using the official `mppx` package
- later, seller-side ACP helpers tied to Meridian checkout flows

It is Meridian-owned code and uses published packages, not the cloned repos at
runtime.

## Env

- `STRIPE_SECRET_KEY`
- `MPP_MASTER_SEED` for Meridian runtime payer accounts
- optionally `TEMPO_TEST_CURRENCY`
- `PORT`

## Run

```bash
npm install
npm run dev
```

## Endpoints

- `GET /health`
- `GET /mpp/paid`
- `POST /mpp/authorize`
- `POST /mpp/execute`

`/mpp/paid` is intentionally a direct MPP-protected resource using `mppx`.
It now supports an optional `recipient` query param for live testing, for
example:

```bash
curl -i "http://localhost:3020/mpp/paid?recipient=0x2222222222222222222222222222222222222222"
```

This should return a real HTTP 402 MPP challenge.

Meridian does not currently expose `mpp` as engine-runtime-ready. The service is
real, and when `MPP_MASTER_SEED` is configured it can execute the official MPP
client payment flow for runtime calls.
