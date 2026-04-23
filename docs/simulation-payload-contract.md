# Simulation Payload Contract

Meridian adapts the MiroFish workflow into a payment-economy simulation:
seed a world, scaffold entities, run agent actions, stream trace events, then
ground reports and chat in the trace. Protocol repos under `ref/` calibrate
fees, latency, settlement domains, and failure modes. They are reference rails,
not the product surface.

## MiroFish Adaptation

- `SimulationConfig.world_seed`, `scenario_prompt`, and `stable_universe`
  define the seeded world.
- Agents, merchants, stablecoin domains, routes, protocol trust, treasury
  posture, and rail P&L are first-class simulation state.
- Memory is explicit data: `AgentMemoryEvent` rows update protocol trust and
  flow into `agent_memory_log`.
- World context is explicit data: `EconomyWorldEvent` rows describe route
  pressure, treasury posture, rebalances, market shifts, and round closures.
- The UI consumes the NDJSON stream through `web/src/lib/simStream.ts`; unknown
  fields may pass through the raw `SimEvent` timeline even when a normalized
  helper projects only the stable core fields.

## Stream Envelope

Each emitted line is one JSON object with `type` and `timestamp`. Round-scoped
events should include `round`; persisted memory/world rows use `round_num`.
Consumers should accept both and preserve unknown fields.

Lifecycle events:

- `setup`: world identity, products, agents, merchants, engine URL, protocols,
  and stablecoin universe.
- `simulation_start`: configured world, rounds, protocols, flow mix, and stable
  universe.
- `round_complete`: active agents, success/failure counts, volume, fees,
  `protocol_attempts`, `route_usage`, `route_pressure`, `treasury_posture`,
  memory count, and `trust_summary`.
- `simulation_complete`: final payload with `world_id`, `simulation_world`,
  `total_transactions`, `total_volume_cents`, `duration_seconds`,
  `protocol_summaries`, `ecosystem_summary`, `route_usage_summary`,
  `route_pressure_summary`, `float_summary`, `treasury_distribution`,
  `treasury_posture_summary`, `rail_pnl_history`, `balances`, `trust_summary`,
  `agent_memory_log`, `world_events`, and optional `llm_usage`.
- `error`, `llm_enabled`, and `graph_enabled`: operational status events.

Transaction and economy events:

- `purchase`: settled buyer transaction with agent, merchant, product,
  protocol, amount, fee, route, pressure, margin, trust, workload, and round.
- `purchase_failed`: failed buyer transaction with route, workload, pressure,
  trust, and error.
- `route_execution`: route settlement record emitted from the economy.
- `balance_update`: balance bucket movement emitted from the economy.
- `rail_pnl_update`: protocol margin, revenue, infrastructure cost, and round.
- `market_snapshot`: protocol merchant count, network effect, congestion,
  reliability, route mix, and round.

Memory and world events:

- `agent_memory`: one `AgentMemoryEvent` for a protocol experience.
- `trust_snapshot`: `trust_summary` by protocol with avg/min/max trust.
- `world_event`: one `EconomyWorldEvent`; important `event_type` values are
  `world_seeded`, `route_pressure`, `treasury_rebalance`,
  `treasury_rebalance_failed`, `treasury_posture`, `round_closed`,
  `merchant_protocol_mix_changed`, and `agent_preference_shift`.
- `merchant_switch`: merchant protocol adoption or removal.
- `agent_preference_shift`: agent preference changed after accumulated memory.
- `treasury_rebalance`: merchant treasury recycling success, also mirrored as a
  `world_event`.

## Dataclass Payloads

### `AgentMemoryEvent`

Source: `_record_agent_memory`. Stream type: `agent_memory`. Final location:
`simulation_complete.agent_memory_log`.

Fields: `round_num`, `agent_id`, `agent_name`, `event_type`, `protocol`,
`workload_type`, `sentiment_delta`, `trust_before`, `trust_after`, `outcome`,
`trust_driver`, `ecosystem_pressure`, `amount_cents`, `merchant_id`,
`merchant_name`, `merchant_reputation`, `product_name`, `route_id`, `reason`.

### `EconomyWorldEvent`

Source: `_record_world_event`. Stream type: `world_event`. Final location:
`simulation_complete.world_events`.

Fields: `round_num`, `event_type`, `summary`, `actor_id`, `protocol`, `data`.

Use `data` for structured context such as route pressure, treasury posture,
trust summaries, rebalance outcomes, merchant switches, and agent preference
shifts. Keep `summary` short enough for timelines and reports.

### `RoundSummary`

Internal per-round aggregate. Streamed through `round_complete` and folded into
`SimulationResult`.

Fields: `round_num`, `transactions`, `route_executions`, `agent_memories`,
`world_events`, `total_volume`, `total_fees`, `success_count`, `fail_count`,
`active_agents`, `protocol_attempts`, `merchant_sales`, `ecosystem`,
`route_usage`, `route_pressure`, `balance_summary`, `treasury_distribution`,
`treasury_posture`.

### `SimulationResult`

Final in-memory result and source for `simulation_complete`.

Fields: `config`, `rounds`, `protocol_summaries`, `trust_summary`,
`agent_memory_log`, `world_events`, `total_transactions`, `total_volume`,
`duration_seconds`, `ecosystem_summary`, `route_usage_summary`,
`route_pressure_summary`, `float_summary`, `treasury_distribution`,
`treasury_posture_summary`, `rail_pnl_history`.

## Frontend Stream Helpers

`web/src/lib/simStream.ts` is the browser-side contract adapter. It normalizes
mixed stream data before updating stores:

- Chunking/parsing: `splitNdjsonChunk`, `finalNdjsonLine`,
  `parseSimulationEvent`.
- Timeline/log text: `normalizeTimelineEvent`, `describeStreamEvent`.
- Memory/world rows: `normalizeAgentMemoryEvent`,
  `normalizeAgentMemoryEvents`, `normalizeWorldEvent`, `normalizeWorldEvents`.
- Summaries: `normalizeTrustSummary`, `normalizeProtocolSummaries`,
  `normalizeEcosystemSummary`, `normalizeBalanceSnapshots`.
- Numeric records: `normalizeNumberRecord`, `normalizeNestedNumberRecord`,
  `normalizeNumberArrayRecord`, `numberFrom`.

When adding a sim payload field, update this file only if the UI needs a typed
projection. Raw events can carry extra fields without a helper change.
