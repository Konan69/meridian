# Meridian

Agentic commerce simulation platform. Runs thousands of AI agents through realistic commerce scenarios across competing payment protocols — measuring which architectures produce better outcomes under different market conditions.

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
   dark theme           5 protocols         50-1000 agents
   D3 graphs            axum + serde        rule-based decisions
   live streaming        SQLite              async concurrent
```

## Quick Start

```bash
# Prerequisites: Rust, Node.js 20+, Python 3.11, uv

# 1. Build and start the commerce engine
cd engine && cargo run -- --port 4080

# 2. In another terminal, start the frontend
cd web && npm install && npm run dev

# 3. In another terminal, run a simulation
cd sim && uv venv --python 3.11 && uv pip install aiohttp
.venv/bin/python -m sim.engine
```

Or use the run script:
```bash
./run.sh
```

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
│   │   ├── protocols/   # ACP, AP2, x402, MPP, ATXP adapters
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
└── CLAUDE.md        # Design context
```

## License

Apache 2.0
