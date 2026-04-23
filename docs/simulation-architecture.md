# Meridian Simulation Architecture

Meridian models an economy of agents choosing between payment protocols. Live
rails are constraints and calibration points; the product surface is the
simulation: agents, merchants, stablecoin domains, routes, protocol trust,
treasury pressure, and emergent adoption.

## Product Contract

Meridian is a simulation of agents initiating transactions across payment
protocols and settlement routes. The core job is to make the ecosystem economy
legible: who bought what, which protocol moved the value, how route pressure and
treasury posture changed, and why agents or merchants changed trust.

Live CDP, Stripe, ATXP, AP2, x402, and related integrations are reference rails
for realism. They should constrain fees, readiness, latency, failures, balances,
and settlement vocabulary, but they are not the product center. Product-facing
work should keep the graph, timeline, reports, and chat focused on the simulated
economy rather than turning Meridian into an SDK console or funding dashboard.

The workbench economy observability surface is part of that contract. Route
ledger, rail P&L, and merchant-switch evidence should stay tied to simulation
store state and payload fields, not drift into provider diagnostics.

## Reference Checkouts

Local references live under `ref/` and are ignored by git.

- `ref/mirofish`: multi-agent simulation workflow reference.
- `ref/deps/*`: protocol and simulation dependency references cloned for local
  inspection, currently AP2, ATXP SDK/CLI, x402, CDP SDK, MPPX, Stripe Node,
  OASIS, and CAMEL.

MiroFish patterns adapted into Meridian:

- Seeded world: a scenario prompt becomes a named economy seed.
- Graph scaffold: entities and relationships are visible before simulation.
- Agent personas: agents carry budgets, preferences, trust, and memory.
- Action stream: each round emits transaction, route, trust, and world events.
- Deep interaction: reports and chat are grounded in the simulation trace.

Reference use rules:

- Borrow workflow shape from `ref/mirofish`, not its domain assumptions.
- Use protocol repos under `ref/deps/*` for settlement vocabulary, latency,
  fee, failure, and readiness constraints.
- Use OASIS and CAMEL as multi-agent economy references for role design,
  interaction loops, and evaluation ideas.
- Do not vendor reference source into Meridian unless a future task explicitly
  needs a small, attributed adaptation.

## Economy Loop

Each simulation round:

1. Selects active buyer agents from remaining budgets.
2. Chooses market opportunities and workload type.
3. Scores feasible payment options across supported protocols and settlement
   routes.
4. Executes the transaction through the engine-facing protocol adapter.
5. Updates balances, route pressure, rail economics, merchant reputation, and
   agent protocol trust.
6. Emits agent memory and world events for visualization and reporting.
7. Lets merchants and agents shift protocol preference based on observed
   economics and accumulated trust.

## Stream Contract

The simulation API streams NDJSON. Important event types:

- `setup`: initial world size, supported protocols, seed metadata.
- `simulation_start`: world identity and configured flow mix.
- `purchase`: settled buyer transaction.
- `purchase_failed`: failed buyer transaction.
- `agent_memory`: per-agent protocol trust update.
- `trust_snapshot`: aggregate trust summary by protocol.
- `world_event`: simulation-level narrative event.
- `route_pressure`: round-level route capacity pressure, mirrored as
  `world_event` data for economy analysis.
- `treasury_rebalance`: merchant treasury recycling between settlement domains,
  also mirrored as `world_event` data.
- `treasury_posture`: merchant preferred-domain shortfall and rebalance
  readiness, mirrored as `world_event` data.
- `merchant_switch`: merchant protocol adoption/removal.
- `agent_preference_shift`: agent preference changed from memory.
- `simulation_complete`: final summaries, balances, memory log, world events.

For field-level payload details, frontend normalization helpers, and the
MiroFish adaptation boundary, see `docs/simulation-payload-contract.md`.

## Autonomous Checkpoints

When an Evo checkpoint is already at benchmark score `1.0`, treat it as the
contract baseline to preserve. Useful autonomous changes should make the
economy more believable, the workbench explanation clearer, or future
regression diagnosis easier; they should not relax static contracts, compile
checks, or build/test commands.

Benchmark traces are part of the handoff between workers. Keep command context,
cache key inputs, and static contract coverage visible so the next worker can
separate a real validation failure from cache setup or timing variance.

## Optimization Target

Future Evo work should optimize for believable ecosystem behavior:

- Protocol choices respond to fees, latency, reliability, capacity, workload,
  and social memory.
- Treasury rebalancing changes route pressure and rail P&L.
- Self-sustainability reports show rebalance outcomes, route pressure, and rail
  margin pressure as economy signals, not just funding diagnostics.
- The UI explains the simulation state through graph, timeline, report, and
  chat without treating funding status as the main product.
- Autonomous workers should continue from repo evidence: pick the next safe
  agent, merchant, route, treasury, report, or visualization improvement, run
  the relevant check, and only stop for a real blocker.
