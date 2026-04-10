# Meridian

Agentic commerce simulation platform. Runs thousands of AI agents through
realistic commerce scenarios across payment protocols while using direct live
integrations only. Meridian models a USDC-centric stablecoin economy with
fragmented balance buckets, route-level settlement behavior, merchant treasury
preferences, and rail P&L. Today, the engine only registers rails with real
direct implementations and exposes the rest with explicit capability reasons.

## Protocols Compared

| Protocol | Maintainer | Layer | Fee Model | Settlement |
|----------|-----------|-------|-----------|------------|
| **ACP** | OpenAI + Stripe | Checkout | 2.9% + 30¢ | ~2,000ms |
| **AP2** | Google | Trust/Auth | 2.5% + 20¢ | ~3,000ms |
| **x402** | Coinbase | Payment | 0.1% | ~200ms |
| **MPP** | Stripe + Tempo | Streaming | 1.5% + 5¢ | ~500ms |
| **ATXP** | Circuit & Chisel | Agent-to-Agent | 0.5% | ~150ms |

## Architecture

```
SvelteKit (:5173) → Rust Engine (:4080) ← Python Simulation
   frontend            commerce            agent orchestration
   dark theme           capability-driven   50-1000 agents
   D3 graphs            axum + serde        rule-based decisions
   live streaming        SQLite              async concurrent
```

## Direct Integration Mode

Meridian no longer boots against placeholder adapter URLs.

- `x402` runs natively inside the engine
- other rails should only be added when they have a real direct integration path
- Creating a checkout session requires an explicit `protocol`
- the simulator discovers the actually supported rails from the engine

### Direct Service Work In Progress

Meridian now contains direct service landing zones for real protocol-owned
paths instead of the old fake localhost adapter contract:

- `services/cdp/` — Coinbase Server Wallet v2 path for x402 buyer and merchant wallets
- `services/atxp/` — official `@atxp/*` SDK path
- `services/stripe/` — official Stripe + `mppx` path
- `services/ap2/` — Meridian-owned AP2 service built on official AP2 types

These are Meridian-owned integration surfaces and are the intended path
forward for adding rails back honestly.

## Stablecoin Economy Model

Meridian is now agent-driven and economy-first:

- agents choose workloads before rails
- buyers hold fragmented stablecoin balances
- merchants have preferred settlement domains and treasury rebalance logic
- route classes apply cost, latency, capacity, and failure pressure
- named rails wrap a smaller set of settlement primitives

### V1 Balance Domains

- `base_usdc`
- `solana_usdc`
- `tempo_usd`
- `stripe_internal_usd`
- `gateway_unified_usdc`

### V1 Workload Mix

- `api_micro`
- `consumer_checkout`
- `treasury_rebalance`

### V1 Settlement Primitives

- `direct_same_domain`
- `batched_nanopayment`
- `tempo_session`
- `stripe_internal_checkout`
- `gateway_unified`
- `cctp_transfer`
- `lifi_routed`

### Required Environment Variables

```bash
export MERIDIAN_PUBLIC_BASE_URL=http://localhost:4080
export CDP_SERVICE_URL=http://localhost:3030

export X402_RPC_URL=...
export CDP_API_KEY_ID=...
export CDP_API_KEY_SECRET=...
export CDP_WALLET_SECRET=...
```

`CDP_API_KEY_ID`, `CDP_API_KEY_SECRET`, and `CDP_WALLET_SECRET` must come from
Coinbase Server Wallet v2. Embedded Wallet credentials are the wrong product
for Meridian's backend-owned x402 flow.

## Quick Start

```bash
# Prerequisites: Rust, Node.js 20+, Python 3.11, uv

# 0. Configure .env with real service credentials

# 1. Start the full local stack in dependency order
./run.sh

# 2. In another terminal, inspect actual runtime capabilities
curl http://localhost:4080/capabilities

# 3. In another terminal, run a simulation
cd sim && .venv/bin/python -m sim.engine
```

Or use the run script:
```bash
./run.sh
```

`run.sh` starts `cdp`, `stripe`, `atxp`, `ap2`, the engine, and the frontend in
dependency order.

## Simulation Output

```
======================================================================
  MERIDIAN SIMULATION REPORT
======================================================================
  Agents: 50 | Rounds: 10 | Duration: 0.1s
  Total Transactions: 131 | Volume: $7,618.50

  Protocol   Txns     Volume       Fees    Fee%     Settle   Micropay
  -----------------------------------------------------------------
  ATXP         27 $    996.30 $    4.90   0.49%      150ms          5
  X402         23 $  1,643.20 $    1.63   0.10%      200ms          6
  MPP          26 $  1,258.20 $   20.00   1.59%      500ms          7
  ACP          28 $  1,739.20 $   58.72   3.38%     2000ms          0
  AP2          27 $  1,981.60 $   54.82   2.77%     3000ms          0
======================================================================
```

## Stack

- **Rust** — Commerce engine (axum, serde, rusqlite, tokio)
- **Python** — Simulation layer (rule-based agents, async HTTP to engine)
- **SvelteKit** — Frontend (Svelte 5, D3.js, Tailwind CSS)

## Project Structure

```
meridian/
├── engine/          # Rust commerce engine
│   ├── src/
│   │   ├── core/        # types, pricing, errors
│   │   ├── protocols/   # x402 native protocol integrations
│   │   └── routes/      # HTTP endpoints
│   └── Cargo.toml
├── sim/             # Python simulation layer
│   ├── sim/
│   │   ├── engine.py    # Simulation orchestrator
│   │   ├── agents.py    # Agent profile generation
│   │   ├── commerce.py  # HTTP client for engine
│   │   └── types.py     # Data types
│   └── pyproject.toml
├── web/             # SvelteKit frontend
│   ├── src/routes/      # Pages and API endpoints
│   └── package.json
├── services/        # Direct provider-owned integration services
└── CLAUDE.md        # Design context
```

## License

Apache 2.0
