# Meridian AP2

Meridian-owned AP2 service built on the official `ap2` types package.

This service does not use the cloned Google sample-role stack at runtime. It
uses the official AP2 data types and implements only the protocol surfaces
Meridian actually needs for runtime mandate creation and settlement receipts.

## Install

```bash
uv sync
```

## Run

```bash
uv run meridian-ap2-service
```

## Required Env

- `AP2_MASTER_SEED`
- optionally `PORT` (defaults to `3040`)

## Endpoints

- `GET /health`
- `POST /ap2/authorize`
- `POST /ap2/settle`

The service returns AP2 `IntentMandate`, `CartMandate`, `PaymentMandate`, and
`PaymentReceipt` objects using the official AP2 types package.

## Offline Protocol Contracts

The offline service tests document the AP2 helper contracts Meridian relies on
without live AP2 credentials. Keep this list aligned with `PYTHONPATH=src
python3 -m unittest discover -s tests -q` and the helper file named here:

- `services/ap2/tests/test_contracts.py` covers AP2 canonical credential hashing in `services/ap2/src/meridian_ap2_direct/contracts.py`.
- `services/ap2/tests/test_contracts.py` covers AP2 nested mandate actor, merchant, and amount settlement semantics in `services/ap2/src/meridian_ap2_direct/contracts.py`.
- `services/ap2/tests/test_contracts.py` covers AP2 settlement mismatch diagnostics for merchant and amount drift in `services/ap2/src/meridian_ap2_direct/contracts.py`.

## Offline Contract Tests

`tests/test_contracts.py` keeps a credential-free settlement contract around the
fields the service depends on before it creates a receipt. It checks that the
actor, merchant, top-level amount, cart total, payment total, and nested payment
merchant fields agree without starting the FastAPI app or calling a payment
provider.
