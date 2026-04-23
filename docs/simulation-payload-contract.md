# Simulation Payload Contract

Meridian adapts the MiroFish workflow into a payment-economy simulation:
seed a world, scaffold entities, run agent actions, stream trace events, then
ground reports and chat in the trace. Protocol repos under `ref/` calibrate
fees, latency, settlement domains, and failure modes. They are reference rails,
not the product surface.

## Simulation Intent

Payloads describe an ecosystem economy, not just API traffic. Agent transaction
attempts, protocol choices, route pressure, treasury posture, trust changes,
merchant switches, and rail P&L must remain visible enough for the frontend to
visualize why the economy moved.

Live protocol details belong in the payload when they change simulated behavior:
settlement domain, readiness, fee, latency, balance, failure, or route capacity.
They should not crowd out the agent/economy story that graph, timeline, reports,
and chat are expected to explain.

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

## Reference Rail Boundary

- `ref/mirofish`: borrow workflow shape only. In Meridian that means seeded
  worlds, visible graph scaffolds, agent personas, action streams, explicit
  memory, and trace-grounded reports/chat.
- `ref/deps/*`: use AP2, ATXP, x402, CDP, MPPX, Stripe, and similar protocol
  repos to keep simulated settlement vocabulary, readiness checks, fees,
  latency, domains, and failure modes plausible.
- OASIS and CAMEL: use as multi-agent economy references for role design,
  interaction loops, market pressure, memory, and evaluation ideas.
- Live integrations constrain the simulation. They are not the product goal.
  Payloads should explain agent/economy behavior first and SDK details only
  when they affect settlement realism.
- Do not paste reference source into docs. Summarize the adapted rule and link
  it to Meridian fields or stream events.

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
  `merchant_protocol_mix_changed`, `agent_preference_shift`, and
  `social_memory_diffusion`.
- `merchant_switch`: merchant protocol adoption or removal.
- `agent_preference_shift`: agent preference changed after accumulated memory.
- `treasury_rebalance`: merchant treasury recycling success, also mirrored as a
  `world_event`.

Merchant switch payloads are durable evidence, not just timeline copy.
`merchant_switch` and `world_event.event_type=merchant_protocol_mix_changed`
carry `merchant_id`, `merchant`, `action`, `protocol`, `round`, `reason`, and
`evidence`.

`reason` is `ecosystem_evidence` when trust, memory, route pressure, treasury
posture, reliability, or margin drives the switch. It is `rail_economics` for
legacy stochastic market churn. Adoption evidence includes `adoption_score`,
`avg_trust`, `recent_memory_signal`, `route_pressure`, `treasury_pressure`, and
`serves_preferred_domain`. Removal evidence includes `removal_risk`,
`avg_trust`, `recent_memory_signal`, `route_pressure`, `reliability`, and
`operator_margin_cents`.

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

## Accounting Units

- `route_usage` and `route_usage_summary` are cents of reserved payment
  principal by route, not transaction counts. Use them for route pressure,
  capacity, and settlement-volume explanations.
- `route_mix` is the per-protocol count of attempted executions by route. Use
  it for rail preference and adoption explanations, not dollar volume.
- `rail_pnl_history` stores one operator-margin snapshot per protocol per
  completed round. The final value should match
  `ecosystem_summary.<protocol>.operator_margin_cents`.
- `total_volume_cents` and `protocol_summaries.<protocol>.total_volume_cents`
  count successful settled principal. Failed attempts can still affect
  `route_usage`, `route_mix`, reliability, and operator margin through
  infrastructure cost.
- Static drift checks keep these labels wired to reports and the web store:
  route usage fields are cents, route mix fields are attempt counts, rail P&L fields are margin-cent snapshots,
  and failed attempts are part of the accounting story even when settled
  volume excludes them.

## Frontend Stream Helpers

`web/src/lib/simStream.ts` is the browser-side contract adapter. It normalizes
mixed stream data before updating stores:

- Chunking/parsing: `splitNdjsonChunk`, `finalNdjsonLine`,
  `parseSimulationEvent`.
- Timeline/log text: `normalizeTimelineEvent`, `describeStreamEvent`.
- Memory/world rows: `normalizeAgentMemoryEvent`,
  `normalizeAgentMemoryEvents`, `normalizeWorldEvent`, `normalizeWorldEvents`.
- Summaries: `normalizeTrustSummary`, `normalizeProtocolSummaries`,
  `normalizeEcosystemSummary`, `normalizeBalanceSnapshots`,
  `normalizeRoutePressureSummaries`, and
  `normalizeTreasuryPostureSummaries`.
- Numeric records: `normalizeNumberRecord`, `normalizeNestedNumberRecord`,
  `normalizeNumberArrayRecord`, `numberFrom`.

When adding a sim payload field, update this file only if the UI needs a typed
projection. Raw events can carry extra fields without a helper change.

## Maintenance Checklist

- Before adding fields, name the economy behavior the field explains: an agent
  initiating a transaction, a protocol outcome, route pressure, treasury
  movement, trust/memory, merchant adoption, or visualization of the ecosystem
  economy.
- New dataclass field: update the relevant `AgentMemoryEvent`,
  `EconomyWorldEvent`, `RoundSummary`, or `SimulationResult` field list.
- New emitted `type`: add it under Stream Envelope and decide whether the UI
  can keep it as raw `SimEvent` or needs a `web/src/lib/simStream.ts` helper.
- New `world_event.event_type`: document it if reports, timelines, or chat use
  it as durable context.
- New frontend helper export: add it under Frontend Stream Helpers.
- After docs changes, run `python3 sim/tests/payload_contract_static.py`.
