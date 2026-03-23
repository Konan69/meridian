# Meridian

Agentic commerce simulation platform. Runs thousands of AI agents through realistic commerce scenarios across competing payment protocols (ACP, AP2, x402, MPP, ATXP) — measuring which architectures produce better outcomes under different market conditions.

## Design Context

### Users
Protocol designers stress-testing their payment protocol against alternatives. Fintech researchers studying agentic commerce dynamics and publishing papers. Developers choosing which protocol to integrate, needing data-driven comparisons. Investors and strategists making bets on which protocol layer wins.

All audiences are technical. They expect precision, reproducibility, and depth. They will spend extended time watching simulations run and analyzing results.

### Brand Personality
Clean, futuristic, authoritative. Stripe-level precision meets Polymarket-level data density. Not flashy — confident through restraint.

### Aesthetic Direction
- **Visual tone:** Clean + futuristic. Generous whitespace, precise typography, subtle animations
- **References:** Polymarket (real-time data, probability-driven), Observable/D3 (explorable visualizations), Stripe Docs (precise, beautiful, code-forward)
- **Anti-references:** Generic dashboards, cluttered admin panels, startup landing pages with stock photos
- **Theme:** Dark default with light mode option. Dark is primary — better for data-dense dashboards and long simulation sessions
- **Colors:** Cool blues + warm ambers. Trust (blue) meets commerce (gold/amber). Financial but not cold. Protocol-specific accent colors for comparison charts

### Emotional Goals
- **Fascination:** "I can't stop watching this" — mesmerizing data flows, evolving knowledge graphs
- **Confidence:** "I trust these results" — clear metrics, reproducible, scientific rigor
- **Discovery:** "I didn't expect that" — surfacing surprising patterns, emergent agent behavior
- **Control:** "I can shape what happens" — tuneable parameters, scenario builder, intervention points

### Design Principles
1. **Data is the interface** — every pixel should communicate information. No decorative elements that don't serve comprehension.
2. **Progressive disclosure** — start with the key insight, let users drill into detail. Never overwhelm on first glance.
3. **Protocol-aware color coding** — each protocol gets a consistent color across all views. Users should recognize ACP vs x402 at a glance.
4. **Real-time feels alive** — simulations should feel like watching a living market, not reading a log file. Smooth transitions, not jarring updates.
5. **Reproducibility is visible** — every simulation shows its parameters, seed, and configuration. Results are always attributable to inputs.

## Stack

- **Commerce Engine:** Rust (axum + serde + rusqlite + sha2 + tokio). Protocol-pluggable. Single binary.
- **Frontend:** SvelteKit 5 + Svelte 5 runes + D3.js v7 + Tailwind CSS + TypeScript
- **Simulation Layer:** Python 3.11 (camel-oasis 0.2.5 + camel-ai 0.2.78 + zep-cloud 3.18.0)
- **Database:** SQLite (embedded via rusqlite, no external services)
- **Knowledge Graph:** Graphiti (self-hosted, Neo4j-backed) for simulation scale. Zep Cloud optional for small demos.
- **Real-time:** sveltekit-sse for live simulation event streaming
- **Charts:** LayerCake (Svelte-native) + raw D3 for force graphs

## Reference Codebases (in parent symphony/ directory)

- `agentic-commerce-protocol/` — ACP spec (OpenAI + Stripe)
- `agentic-commerce-demo/` — ACP reference implementation (TypeScript)
- `ap2-protocol/` — AP2 spec (Google)
- `x402-protocol/` — x402 spec + SDKs (Coinbase)
- `MiroFish/` — Swarm prediction engine (inspiration for UI patterns, graph visualization, profile generation)
- `oasis/` — OASIS social simulation platform (camel-oasis source, visualization patterns)
- `elixir/` — Symphony orchestrator (inspiration for workspace/retry patterns only)

## Protocol Adapters

Each protocol is implemented as an adapter behind a shared interface:

| Protocol | Maintainer | Layer | Adapter Source |
|----------|-----------|-------|---------------|
| ACP | OpenAI + Stripe | Checkout | Torn from `agentic-commerce-demo/` |
| AP2 | Google | Trust/Auth | Built from `ap2-protocol/` spec |
| x402 | Coinbase | Payment (stateless) | Built from `x402-protocol/` spec + SDK |
| MPP | Stripe + Tempo | Payment (streaming) | Built from Stripe docs |
| ATXP | Circuit & Chisel | Agent-to-agent | Modeled from public mandate spec |

## Commands

```bash
# Commerce engine (Rust)
cd engine && cargo run -- --port 4080    # single binary, no deps

# Simulation layer (Python)
cd sim && pip install -e . && python -m sim.engine    # calls engine on :4080

# Frontend (SvelteKit)
cd web && npm install && npm run dev    # :5173
```
